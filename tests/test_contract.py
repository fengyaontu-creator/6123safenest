"""Contract agent end-to-end tests — B."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents import AgentInput, AgentOutput
from agents.contract_agent import analyze_contract_text, assess_contract
from tools.vector_store import ContractKnowledgeBase

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cea_standard_lease"
HDB_TEMPLATE = DATA_DIR / "Tenancy Agreement Template for HDB Flats.pdf"


@pytest.fixture(scope="module")
def kb_seeded() -> ContractKnowledgeBase:
    """单份 HDB 模板 ephemeral kb,模块级共享避免重复 ingest。"""
    kb = ContractKnowledgeBase(
        collection_name="test_contract_agent_kb",
        persist_dir=None,
    )
    kb.ingest_pdf(HDB_TEMPLATE, doc_id="hdb_template")
    return kb


# ---------------------------------------------------------------------------
# No contract path: graceful degradation
# ---------------------------------------------------------------------------

def test_no_contract_returns_unknown(kb_seeded: ContractKnowledgeBase):
    output = assess_contract(
        AgentInput(address="Jurong West", rent=2000),
        kb=kb_seeded,
    )

    assert isinstance(output, AgentOutput)
    assert output.agent_name == "contract_agent"
    assert output.risk_level == "unknown"
    assert output.score is None
    assert any("no contract" in f.lower() for f in output.findings)
    assert any("upload" in r.lower() or "--contract" in r.lower() for r in output.recommendations)


def test_missing_contract_path_returns_unknown(kb_seeded: ContractKnowledgeBase):
    output = assess_contract(
        AgentInput(
            address="Jurong West",
            rent=2000,
            contract_path="does/not/exist.pdf",
        ),
        kb=kb_seeded,
    )

    assert output.risk_level == "unknown"
    assert any("not found" in f.lower() for f in output.findings)


# ---------------------------------------------------------------------------
# Real PDF contract (HDB template = "model" contract)
# ---------------------------------------------------------------------------

def test_real_pdf_contract_runs_full_pipeline(kb_seeded: ContractKnowledgeBase):
    """用 HDB CEA 模板自己当合同 — 应该一切都低风险。"""
    output = assess_contract(
        AgentInput(
            address="Jurong West",
            rent=2000,
            contract_path=str(HDB_TEMPLATE),
        ),
        kb=kb_seeded,
    )

    assert output.risk_level in {"low", "medium"}  # 不能是 high 或 unknown
    assert output.score is not None
    assert output.score > 40  # 至少不能很糟
    # 应该有针对每类条款的 finding
    assert len(output.findings) >= 3
    assert any("contract risk" in f.lower() for f in output.findings)


def test_pdf_contract_evidence_includes_cea_references(
    kb_seeded: ContractKnowledgeBase,
):
    output = assess_contract(
        AgentInput(contract_path=str(HDB_TEMPLATE), rent=2000),
        kb=kb_seeded,
    )

    # 应该至少有一条 CEA 来源引用
    cea_refs = [e for e in output.evidence if "cea reference" in e.lower()]
    assert len(cea_refs) >= 1


# ---------------------------------------------------------------------------
# Direct contract_text input (web upload path)
# ---------------------------------------------------------------------------

def test_contract_text_with_high_risk_clauses(kb_seeded: ContractKnowledgeBase):
    """模拟一份恶霸合同 — 应该被识别为 high 风险。"""
    bad_contract = (
        "TENANCY AGREEMENT.\n"
        "1. Security deposit equivalent to 6 months rent shall be paid upfront.\n"
        "2. This agreement is non-cancellable; no early termination is permitted.\n"
        "3. The tenant shall be responsible for all repairs and maintenance.\n"
        "4. Tenant shall pay all utilities without limit.\n"
    )

    output = assess_contract(
        AgentInput(
            contract_text=bad_contract,
            contract_file_name="bad_contract.pdf",
            rent=2000,
        ),
        kb=kb_seeded,
    )

    assert output.risk_level in {"medium", "high"}
    # 至少应该有 findings 提到高严重度问题
    assert any("FLAG" in f or "high" in f.lower() for f in output.findings)
    # data 字段含完整的 clause_assessments
    assessments = output.data["clause_assessments"]
    high_severity = [a for a in assessments if a["severity"] == "high"]
    assert len(high_severity) >= 2  # deposit + termination 至少两条 high


def test_contract_text_with_clean_clauses(kb_seeded: ContractKnowledgeBase):
    """模拟一份正规合同 — 应该是 low 风险。"""
    clean_contract = (
        "TENANCY AGREEMENT.\n"
        "1. Security deposit shall be 2 months rent, refundable on tenancy end.\n"
        "2. Either party may terminate with 2 months written notice after 12 months.\n"
        "3. Tenant shall maintain the premises subject to fair wear and tear.\n"
        "4. Tenant pays all utilities up to S$300 per month.\n"
    )

    output = assess_contract(
        AgentInput(
            contract_text=clean_contract,
            contract_file_name="clean_contract.pdf",
            rent=2000,
        ),
        kb=kb_seeded,
    )

    assert output.risk_level == "low"
    assert output.score is not None
    assert output.score >= 70


# ---------------------------------------------------------------------------
# AgentOutput schema sanity
# ---------------------------------------------------------------------------

def test_output_strictly_follows_agent_output_schema(
    kb_seeded: ContractKnowledgeBase,
):
    output = assess_contract(
        AgentInput(contract_path=str(HDB_TEMPLATE), rent=2000),
        kb=kb_seeded,
    )

    assert output.agent_name == "contract_agent"
    assert output.risk_level in {"low", "medium", "high", "unknown"}
    assert output.summary
    assert isinstance(output.findings, list)
    assert isinstance(output.evidence, list)
    assert isinstance(output.recommendations, list)
    assert isinstance(output.data, dict)


def test_data_field_is_orchestrator_friendly(kb_seeded: ContractKnowledgeBase):
    """data 字段应该是 JSON-serialisable, orchestrator 会序列化。"""
    import json

    output = assess_contract(
        AgentInput(contract_path=str(HDB_TEMPLATE), rent=2000),
        kb=kb_seeded,
    )

    # 不抛异常说明可以序列化
    serialised = json.dumps(output.data, default=str)
    assert "overall_score" in serialised


# ---------------------------------------------------------------------------
# analyze_contract_text (the LLM tool)
# ---------------------------------------------------------------------------

def test_analyze_contract_text_returns_structured_dict():
    """ADK FunctionTool 入口 - 用 default kb 跑(可能慢点首次)。"""
    text = (
        "Security deposit shall be 2 months rent. "
        "Tenant shall maintain subject to fair wear and tear."
    )

    result = analyze_contract_text(text)

    assert result["status"] == "ok"
    assert result["overall_level"] in {"low", "medium", "high"}
    assert isinstance(result["clause_assessments"], list)
    assert isinstance(result["missing_clause_types"], list)


def test_analyze_contract_text_empty_input():
    result = analyze_contract_text("")

    assert result["status"] == "no_contract"
    assert result["overall_level"] == "unknown"
    assert result["overall_score"] is None


def test_analyze_contract_text_irrelevant_input():
    result = analyze_contract_text("Just some random words about cats.")

    assert result["status"] == "no_clauses_detected"
    assert result["overall_level"] == "unknown"
