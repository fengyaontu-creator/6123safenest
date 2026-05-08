"""Contract agent — Singapore 租赁合同条款审查 (B).

完整 pipeline:
1. 拿到合同文本 (contract_text 直接给 / contract_path 解析 PDF)
2. 抽取 4 类核心条款 (deposit / termination / repairs / utilities)
3. 跟 CEA 标准租约知识库做语义对比
4. 模式检测 + 语义偏离 → 每条 clause 的 severity 评估
5. 汇总成 ContractRiskSummary, 转成 AgentOutput 给 orchestrator
"""

from __future__ import annotations

import logging
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
from tools.pdf_parser import extract_pages, extract_text
from tools.vector_store import ContractKnowledgeBase, seed_from_cea_templates

logger = logging.getLogger(__name__)

# 持久化 kb 单例: 进程内复用,避免每次 assess 都重新初始化 Chroma
_kb_cache: ContractKnowledgeBase | None = None


def _get_default_kb() -> ContractKnowledgeBase:
    """取持久化的 kb 单例,首次调用时按需 seed CEA 模板。"""
    global _kb_cache
    if _kb_cache is None:
        _kb_cache = ContractKnowledgeBase(persist_dir=settings.chroma_persist_dir)
        if _kb_cache.stats()["chunk_count"] == 0:
            logger.info("Seeding CEA standard templates into vector store (first run)...")
            seed_from_cea_templates(_kb_cache)
    return _kb_cache


def _load_contract_pages(request: AgentInput) -> tuple[list[str], list[str]]:
    """从 request 里拿合同文本并切页。

    Returns:
        (pages, evidence_lines) — pages 用于后续 pipeline,
        evidence 给 AgentOutput 用。
    """
    evidence: list[str] = []

    # 优先级 1: 用户直接给了合同文本 (web 上传走 adk_apps 的 PDF 提取过的)
    if request.contract_text:
        evidence.append(
            f"Contract text from upload: {request.contract_file_name or 'uploaded file'}"
        )
        # 没有页码概念,把整段当一页
        return ([request.contract_text], evidence)

    # 优先级 2: contract_path 文件路径 (CLI 场景)
    if request.contract_path:
        path = Path(request.contract_path)
        if not path.exists():
            return ([], [f"Contract path provided but file not found: {path}"])
        pages = extract_pages(path)
        if not pages or all(not p.strip() for p in pages):
            # PDF 解析失败 / 扫描件 / 加密
            return ([], [f"Could not extract text from {path} (encrypted or scanned PDF?)"])
        evidence.append(f"Contract file: {path.name}")
        return (pages, evidence)

    # 优先级 3: contract_file_name 但没有 text/path → 文件已上传但文本提取失败
    if request.contract_file_name:
        return (
            [],
            [f"Contract file uploaded ({request.contract_file_name}) but text not available."],
        )

    return ([], ["No contract provided."])


def _placeholder_output(reason: str, request: AgentInput) -> AgentOutput:
    """没有合同文本可分析时的优雅降级输出。"""
    return AgentOutput(
        agent_name="contract_agent",
        summary=f"Contract review skipped: {reason}",
        risk_level="unknown",
        score=None,
        findings=[reason],
        evidence=[],
        recommendations=[
            "Provide a contract PDF (CLI: --contract path/to/file.pdf, "
            "or upload via the web UI)."
        ],
        data={
            "contract_path": request.contract_path,
            "contract_file_name": request.contract_file_name,
            "contract_text_available": bool(request.contract_text),
        },
    )


def _format_findings(summary: ContractRiskSummary) -> list[str]:
    """把 ContractRiskSummary 转成给租客看的 findings 列表。"""
    findings: list[str] = []

    # 总体一句
    findings.append(
        f"Overall contract risk: {summary.overall_level.upper()} "
        f"({summary.overall_score}/100)."
    )

    # 每条 clause 的核心结论
    for assessment in summary.assessments:
        severity_icon = {"low": "OK", "medium": "WARN", "high": "FLAG"}[assessment.severity]
        findings.append(
            f"[{severity_icon}] {assessment.clause_type}: "
            f"{assessment.risk_reasons[0] if assessment.risk_reasons else 'reviewed'}"
        )

    # 缺失的 clause type
    if summary.missing_clause_types:
        findings.append(
            f"Missing clauses: {', '.join(summary.missing_clause_types)} — "
            "no terms detected for these aspects."
        )

    return findings


def _format_recommendations(summary: ContractRiskSummary) -> list[str]:
    """从风险评估提取 actionable 建议。"""
    recs: list[str] = []

    # 高严重度 clause 的具体建议
    for assessment in summary.assessments:
        if assessment.severity == "high":
            # 取该 clause 的第一条理由作为可操作建议
            if assessment.risk_reasons:
                recs.append(
                    f"[{assessment.clause_type}] {assessment.risk_reasons[0]}"
                )

    # 缺失条款的兜底建议
    if summary.missing_clause_types:
        recs.append(
            f"Request the landlord to add explicit terms for: "
            f"{', '.join(summary.missing_clause_types)}."
        )

    if not recs:
        recs.append("Contract terms appear within standard range. Always verify in person before signing.")

    return recs


def assess_contract(
    input_data: AgentInput | dict[str, Any],
    *,
    kb: ContractKnowledgeBase | None = None,
) -> AgentOutput:
    """运行完整的合同风险评估,返回 AgentOutput。

    Args:
        input_data: AgentInput 或 dict
        kb: 可选向量库 (测试用); 不传走默认持久化 kb

    Returns:
        AgentOutput, 含 findings / risk_level / score / recommendations。
        无合同时优雅降级返回 unknown。
    """
    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)

    pages, evidence = _load_contract_pages(request)
    if not pages:
        return _placeholder_output(evidence[0] if evidence else "no contract", request)

    # Pipeline: 抽取 → 对比 → 评分
    clauses = extract_clauses(pages)
    if not clauses:
        return _placeholder_output(
            "Contract was parsed but no recognised clause types were found.",
            request,
        )

    target_kb = kb if kb is not None else _get_default_kb()
    comparisons = compare_to_cea_standard(clauses, kb=target_kb)
    summary = summarize_contract_risk(comparisons, extracted_clauses=clauses)

    return AgentOutput(
        agent_name="contract_agent",
        summary=(
            f"Contract risk: {summary.overall_level} "
            f"(score {summary.overall_score}/100). "
            + (summary.overall_reasons[0] if summary.overall_reasons else "")
        ),
        risk_level=summary.overall_level,
        score=summary.overall_score,
        findings=_format_findings(summary),
        evidence=evidence
        + [
            f"CEA reference: {a.cea_source}"
            for a in summary.assessments
            if a.cea_source and "<none>" not in a.cea_source
        ],
        recommendations=_format_recommendations(summary),
        data={
            "contract_path": request.contract_path,
            "contract_file_name": request.contract_file_name,
            "overall_score": summary.overall_score,
            "overall_level": summary.overall_level,
            "missing_clause_types": summary.missing_clause_types,
            "clause_assessments": [
                {
                    "clause_type": a.clause_type,
                    "severity": a.severity,
                    "score": a.score,
                    "risk_reasons": a.risk_reasons,
                    "sample_snippet": a.sample_snippet,
                    "cea_reference_snippet": a.cea_reference_snippet,
                    "cea_source": a.cea_source,
                    "similarity": a.similarity,
                }
                for a in summary.assessments
            ],
        },
    )


# ---------------------------------------------------------------------------
# ADK LlmAgent
# ---------------------------------------------------------------------------

def analyze_contract_text(contract_text: str) -> dict[str, Any]:
    """ADK 工具: 输入合同文本,跑完整 pipeline 返回结构化风险报告。

    LLM 直接调用这个工具拿到所有结果, 然后按 AgentOutput schema 输出 JSON。

    Args:
        contract_text: 合同正文 (来自 session state 的 contract_text)

    Returns:
        含 overall_score / overall_level / clause_assessments / missing_clause_types
        的 dict, LLM 据此组装 final AgentOutput。
    """
    if not contract_text or not contract_text.strip():
        return {
            "status": "no_contract",
            "message": "No contract text provided.",
            "overall_level": "unknown",
            "overall_score": None,
            "clause_assessments": [],
            "missing_clause_types": ["deposit", "termination", "repairs", "utilities"],
        }

    pages = [contract_text]
    clauses = extract_clauses(pages)
    if not clauses:
        return {
            "status": "no_clauses_detected",
            "message": "No recognised clause types found in the contract text.",
            "overall_level": "unknown",
            "overall_score": None,
            "clause_assessments": [],
            "missing_clause_types": ["deposit", "termination", "repairs", "utilities"],
        }

    kb = _get_default_kb()
    comparisons = compare_to_cea_standard(clauses, kb=kb)
    summary = summarize_contract_risk(comparisons, extracted_clauses=clauses)

    return {
        "status": "ok",
        "overall_level": summary.overall_level,
        "overall_score": summary.overall_score,
        "overall_reasons": summary.overall_reasons,
        "missing_clause_types": summary.missing_clause_types,
        "clause_assessments": [
            {
                "clause_type": a.clause_type,
                "severity": a.severity,
                "score": a.score,
                "risk_reasons": a.risk_reasons,
                "sample_snippet": a.sample_snippet,
                "cea_reference": a.cea_reference_snippet,
                "cea_source": a.cea_source,
            }
            for a in summary.assessments
        ],
    }


CONTRACT_AGENT_INSTRUCTION = """\
You review Singapore rental contracts for unfair clauses and CEA standard deviations.

Workflow:
1. Read the contract text from session state ({contract_text?}).
2. Call ``analyze_contract_text`` once with the full contract text.
3. The tool returns structured risk data with per-clause severity ratings and
   missing clause warnings — use this directly. Do NOT invent your own
   severity ratings or risk scores.
4. Format the result as a tenant-facing JSON AgentOutput.

Available data from session state:
  Rental address: {address?}
  Monthly rent (SGD): {rent?}
  Contract file name: {contract_file_name?}
  Extracted contract text: {contract_text?}

If no contract text is available, output risk_level "unknown", score null, and
recommend the user upload a contract.
"""


def create_contract_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="contract_agent",
        model=model,
        instruction=CONTRACT_AGENT_INSTRUCTION + "\n" + INTERNAL_JSON_OUTPUT_INSTRUCTION,
        tools=[FunctionTool(analyze_contract_text)],
        output_key="contract_output",
    )


contract_agent = create_contract_agent()


__all__ = [
    "analyze_contract_text",
    "assess_contract",
    "contract_agent",
    "create_contract_agent",
]
