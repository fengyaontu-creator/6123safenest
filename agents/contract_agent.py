"""Contract agent with RAG-based clause review — B.

Two modes:
  1. Deterministic (``assess_contract``) — for CLI / tests.  Uses Chroma KB
     to retrieve CEA standard clauses and compares them against the uploaded
     contract via lightweight keyword-overlap heuristics (LLM optional).
  2. ADK (``create_contract_agent``) — LlmAgent with a ``search_cea_clause``
     tool that lets the LLM query the CEA knowledge base directly.

Edge cases handled:
  - No contract file → skip, risk_level=unknown
  - PDF parsing failure → graceful degradation
  - KB retrieval returns 0 results → LLM common-sense fallback
  - Contract text < 100 chars → skip
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION
from agents.contract_clauses import extract_clauses
from agents.contract_compare import compare_to_cea_standard
from agents.contract_risk import (
    ClauseRiskAssessment,
    ContractRiskSummary,
    summarize_contract_risk,
)
from config import settings
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from tools.vector_store import (
    ContractKnowledgeBase,
    SearchResult,
    seed_from_cea_templates,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Clause extraction — key rental contract sections
# ---------------------------------------------------------------------------
CLAUSE_LABELS: dict[str, str] = {
    "deposit": "security deposit / rental deposit",
    "termination": "early termination / break lease",
    "maintenance": "repair / maintenance responsibility",
    "utilities": "utilities / PUB / electricity / water charges",
}

# Regex patterns to locate each clause type in raw contract text.
# Each pattern captures UP TO 500 characters after the anchor.
CLAUSE_PATTERNS: dict[str, str] = {
    "deposit": r"(?i)(security\s+deposit|rental\s+deposit|deposit\s+(of|amount)|shall\s+deposit).{0,500}",
    "termination": r"(?i)(termination|early\s+termination|break\s+(the\s+)?lease|notice\s+period).{0,500}",
    "maintenance": r"(?i)(repair|maintenance|keep\s+in\s+good|tenant\s+shall\s+(repair|keep)).{0,500}",
    "utilities": r"(?i)(utilit(y|ies)|PUB|electricity|water\s+(charge|bill|supply)|gas\s+supply).{0,500}",
}

# ---------------------------------------------------------------------------
# Lightweight clause comparison (no LLM required)
# ---------------------------------------------------------------------------


def _extract_clause_text(contract_text: str, clause_key: str) -> str | None:
    """Extract a contract snippet for *clause_key* using regex heuristics."""
    pattern = CLAUSE_PATTERNS.get(clause_key)
    if not pattern:
        return None
    match = re.search(pattern, contract_text, flags=re.DOTALL)
    return match.group(0).strip() if match else None


def _keyword_overlap_score(user_clause: str, ref_clause: str) -> float:
    """Score 0‑100 based on shared keyword overlap between two texts.

    Higher = more similar (less risk).  Lower = more divergence (higher risk).
    """
    def _keywords(text: str) -> set[str]:
        words = re.findall(r"[a-zA-Z]{4,}", text.lower())
        stopwords = {
            "this", "that", "with", "shall", "from", "they", "have",
            "been", "were", "their", "which", "each", "also", "after",
            "upon", "same", "such", "then", "than", "other", "into",
        }
        return {w for w in words if w not in stopwords}

    user_kw = _keywords(user_clause)
    ref_kw = _keywords(ref_clause)
    if not ref_kw:
        return 50.0  # neutral — no reference basis
    overlap = len(user_kw & ref_kw)
    return round(min(overlap / len(ref_kw), 1.0) * 100, 1)


def _compare_clause_with_cea(
    clause_key: str,
    contract_text: str,
    kb: ContractKnowledgeBase,
    *,
    k: int = 3,
) -> dict[str, Any]:
    """Compare one clause type against the CEA knowledge base.

    Returns:
        ``{"clause_key": str, "found": bool, "user_text": str|None,
           "ref_results": list, "deviation_score": float|None,
           "risk_note": str|null}``
    """
    user_text = _extract_clause_text(contract_text, clause_key)
    user_label = CLAUSE_LABELS.get(clause_key, clause_key)

    refs = kb.search(user_label, k=k)
    if not refs:
        return {
            "clause_key": clause_key,
            "found": user_text is not None,
            "user_text": user_text,
            "ref_results": [],
            "deviation_score": None,
            "risk_note": "No CEA reference clauses found for comparison." if user_text else None,
        }

    # Compute overlap score against each reference, take the best (most similar)
    best_score = 0.0
    if user_text:
        for ref in refs:
            score = _keyword_overlap_score(user_text, ref.text)
            if score > best_score:
                best_score = score
        # Invert: deviation = 100 - similarity.  0 = perfect match (low risk),
        # 100 = no overlap at all (high risk).
        deviation = round(100.0 - best_score, 1)
    else:
        deviation = None

    risk_note = None
    if deviation is not None:
        if deviation >= 60:
            risk_note = (
                f"The '{clause_key}' clause differs substantially from the CEA "
                "standard.  Review carefully before signing."
            )
        elif deviation >= 30:
            risk_note = (
                f"The '{clause_key}' clause has moderate differences from the CEA "
                "standard.  Confirm the terms with the landlord."
            )

    return {
        "clause_key": clause_key,
        "found": user_text is not None,
        "user_text": user_text,
        "ref_results": [
            {"document": r.document, "page": r.page, "score": round(r.score, 4),
             "text": r.text[:150] + ("..." if len(r.text) > 150 else "")}
            for r in refs
        ],
        "deviation_score": deviation,
        "risk_note": risk_note,
    }


# ---------------------------------------------------------------------------
# Deterministic assess_contract
# ---------------------------------------------------------------------------


def assess_contract(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    """Run deterministic contract assessment (CLI / tests).

    Steps:
        1. Parse contract text (from input or file).
        2. Seed CEA knowledge base.
        3. Compare 4 key clauses against CEA standards.
        4. Derive risk score and recommendations.
    """
    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)

    evidence: list[str] = []
    recommendations: list[str] = []
    clause_results: list[dict[str, Any]] = []

    # ---- Step 1: get contract text -----------------------------------------
    contract_text = request.contract_text
    if not contract_text and request.contract_path:
        path = Path(request.contract_path)
        if path.exists():
            try:
                from tools.pdf_parser import extract_text as pdf_extract_text
                contract_text = pdf_extract_text(path)
                evidence.append(str(path))
            except Exception as exc:
                logger.warning("PDF parse failed for %s: %s", path, exc)
                evidence.append(f"{path} (parse failed)")

    # No contract at all
    if not contract_text:
        return AgentOutput(
            agent_name="contract_agent",
            summary=(
                "No contract file was provided.  Upload or specify a rental "
                "contract PDF to receive clause-by-clause risk analysis."
            ),
            risk_level="unknown",
            score=None,
            findings=["No contract text available for review."],
            evidence=evidence,
            recommendations=[
                "Upload the rental contract PDF for automated clause review.",
                "In the meantime, manually verify deposit, termination, repair, "
                "and utility clauses against the CEA standard lease templates "
                "at cea.gov.sg.",
            ],
            data={
                "contract_path": request.contract_path,
                "contract_text_available": False,
            },
        )

    # Contract text too short
    if len(contract_text.strip()) < 100:
        return AgentOutput(
            agent_name="contract_agent",
            summary=(
                "The uploaded contract appears too short for meaningful analysis. "
                "Please check that the PDF contains the full tenancy agreement."
            ),
            risk_level="unknown",
            score=None,
            findings=["Contract text is too short (< 100 characters) for clause review."],
            evidence=evidence,
            recommendations=[
                "Ensure the uploaded PDF contains the full tenancy agreement.",
                "Rescan or re-upload the document.",
            ],
            data={
                "contract_text_chars": len(contract_text),
                "contract_text_preview": contract_text[:200],
            },
        )

    # ---- Step 2: seed CEA knowledge base ------------------------------------
    try:
        kb = ContractKnowledgeBase(persist_dir=None)  # ephemeral
        seed_from_cea_templates(kb)
        kb_available = kb.stats()["chunk_count"] > 0
    except Exception as exc:
        logger.warning("CEA KB seeding failed: %s", exc)
        kb_available = False

    if not kb_available:
        # Degrade gracefully — still reviewable by LLM in ADK mode
        return AgentOutput(
            agent_name="contract_agent",
            summary=(
                "Contract text is available, but the CEA knowledge base could "
                "not be loaded for automated comparison."
            ),
            risk_level="unknown",
            score=None,
            findings=["Contract text available but CEA comparison engine unavailable."],
            evidence=evidence,
            recommendations=[
                "Re-run when the CEA template PDFs are accessible.",
                "Manually compare the contract against CEA standard lease templates.",
            ],
            data={
                "contract_text_chars": len(contract_text),
                "kb_available": False,
            },
        )

    # ---- Step 3: compare 4 key clauses --------------------------------------
    for clause_key in CLAUSE_LABELS:
        try:
            result = _compare_clause_with_cea(clause_key, contract_text, kb)
            clause_results.append(result)
        except Exception as exc:
            logger.warning("Clause comparison failed for %s: %s", clause_key, exc)
            clause_results.append({
                "clause_key": clause_key,
                "found": False,
                "error": str(exc),
            })

    # ---- Step 4: compute risk -----------------------------------------------
    scores = [
        r["deviation_score"]
        for r in clause_results
        if r.get("deviation_score") is not None
    ]
    if not scores:
        overall_score = None
        risk_level = "unknown"
    else:
        overall_score = round(sum(scores) / len(scores), 1)
        if overall_score >= 60:
            risk_level = "high"
        elif overall_score >= 30:
            risk_level = "medium"
        else:
            risk_level = "low"

    # Build findings from clause results
    findings: list[str] = []
    for r in clause_results:
        found_mark = "[OK]" if r.get("found") else "[--]"
        clause = r["clause_key"]
        dev = r.get("deviation_score")
        note = r.get("risk_note")
        if dev is not None:
            findings.append(f"[{found_mark}] {clause}: deviation={dev}/100")
        else:
            findings.append(f"[{found_mark}] {clause}: not found in contract")
        if note:
            recommendations.append(note)

    # Add fallback recommendation
    if overall_score is not None and overall_score >= 30:
        recommendations.append(
            "Consider having a legal professional review the contract before "
            "signing, especially the clauses flagged above."
        )
    if not recommendations:
        recommendations.append(
            "Contract appears broadly aligned with CEA standards.  "
            "Still review all clauses before signing."
        )

    evidence.append("CEA standard lease knowledge base (Chroma)")


def _placeholder_output(reason: str, request: AgentInput) -> AgentOutput:
    """没有合同文本可分析时的优雅降级输出。"""
    return AgentOutput(
        agent_name="contract_agent",
        summary=f"Contract risk is {risk_level} based on clause comparison.",
        risk_level=risk_level,
        score=overall_score,
        findings=findings,
        evidence=evidence,
        recommendations=recommendations,
        data={
            "contract_text_chars": len(contract_text),
            "contract_text_preview": contract_text[:500],
            "clause_results": clause_results,
            "kb_chunks": kb.stats()["chunk_count"],
        },
    )


# ---------------------------------------------------------------------------
# ADK tool & agent
# ---------------------------------------------------------------------------


def search_cea_clause(query: str) -> dict[str, Any]:
    """Search the CEA standard lease knowledge base for a clause description.

    Use this tool when you need to compare a contract clause against the CEA
    standard.  The query should be a short phrase describing the clause type
    (e.g. "security deposit amount").

    Args:
        query: Clause description to look up in the CEA knowledge base.

    Returns:
        Top 3 matching CEA standard clauses with their source documents,
        page numbers, and text content.
    """
    kb = ContractKnowledgeBase(persist_dir=settings.chroma_persist_dir)
    if kb.stats()["chunk_count"] == 0:
        seed_from_cea_templates(kb)

    results = kb.search(query, k=3)
    if not results:
        return {"found": False, "query": query, "results": []}

    return {
        "found": True,
        "query": query,
        "results": [
            {
                "document": r.document,
                "page": r.page,
                "text": r.text[:800],
                "relevance": round(r.score, 4),
            }
            for r in results
        ],
    }


def _build_contract_instruction() -> str:
    labels = "\n".join(
        f"  - {key}: {desc}" for key, desc in CLAUSE_LABELS.items()
    )
    return (
        "Review Singapore rental contracts clause-by-clause.  The user may "
        "have uploaded a PDF from the Web (contract_text in session state) "
        "or provided a file path via CLI (contract_path in session state).\n\n"
        "**Workflow**\n"
        "1. Confirm contract text is available.  If it is `contract_path` without "
        "   text, inform the user that the CLI did not extract text.\n"
        "2. Use the `search_cea_clause` tool to look up each of these clause "
        "   types against the CEA standard:\n"
        f"{labels}\n"
        "3. Compare each clause in the user's contract against the CEA "
        "   references returned by the tool.\n"
        "4. Assign a deviation score (0 = matches CEA, 100 = completely "
        "   different or missing) to each clause type.\n"
        "5. Summarize overall risk, key deviations, and practical next steps.\n\n"
        "**Scoring guidelines**\n"
        "- Deviation < 30: broadly compliant, low risk\n"
        "- Deviation 30‑60: moderate differences, review recommended\n"
        "- Deviation > 60: substantial divergence, high risk — flag as urgent\n\n"
        "Uploaded contract file name: {contract_file_name?}\n"
        "Extracted uploaded contract text: {contract_text?}\n"
        + INTERNAL_JSON_OUTPUT_INSTRUCTION
    )


def create_contract_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="contract_agent",
        model=model,
        instruction=_build_contract_instruction(),
        tools=[FunctionTool(search_cea_clause)],
        output_key="contract_output",
    )


contract_agent = create_contract_agent()


__all__ = [
    "assess_contract",
    "contract_agent",
    "create_contract_agent",
    "search_cea_clause",
]

