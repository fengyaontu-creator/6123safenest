"""Contract risk scoring tests — B."""

from __future__ import annotations

import pytest

from agents.contract_clauses import Clause, extract_clauses
from agents.contract_compare import ClauseComparison
from agents.contract_risk import (
    ClauseRiskAssessment,
    ContractRiskSummary,
    assess_clause_risk,
    summarize_contract_risk,
)


def _make_clause(clause_type: str, snippet: str, page: int = 1) -> Clause:
    return Clause(
        clause_type=clause_type,  # type: ignore[arg-type]
        snippet=snippet,
        source_page=page,
        method="keyword",
        confidence=0.7,
        matched_keyword="test",
    )


def _make_comparison(
    clause_type: str,
    snippet: str,
    similarity: float = 0.6,
    cea_ref: str = "Standard CEA reference text.",
) -> ClauseComparison:
    return ClauseComparison(
        clause=_make_clause(clause_type, snippet),
        cea_reference_snippet=cea_ref,
        cea_source_document="hdb_template",
        cea_source_page=4,
        similarity=similarity,
        raw_distance=1.0,
    )


# ---------------------------------------------------------------------------
# Deposit
# ---------------------------------------------------------------------------

def test_deposit_2_months_is_low_risk():
    comp = _make_comparison(
        "deposit",
        "The tenant shall pay 2 months rent as security deposit.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "low"
    assert a.score >= 80


def test_deposit_4_months_is_medium_risk():
    comp = _make_comparison(
        "deposit",
        "The tenant shall pay 4 months rent as security deposit.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "medium"
    assert "4 months exceeds" in " ".join(a.risk_reasons)


def test_deposit_6_months_is_high_risk():
    comp = _make_comparison(
        "deposit",
        "Security deposit equivalent to 6 months rent.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "high"
    assert a.score < 30


def test_deposit_word_form_months():
    """单词形式的月数('two months')也应该被识别。"""
    comp = _make_comparison(
        "deposit",
        "Security deposit shall be two months rent.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "low"


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------

def test_termination_non_cancellable_is_high_risk():
    comp = _make_comparison(
        "termination",
        "This agreement is non-cancellable for the entire term.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "high"
    assert any("non-cancellable" in r.lower() for r in a.risk_reasons)


def test_termination_no_early_termination_is_high_risk():
    comp = _make_comparison(
        "termination",
        "The tenant shall not terminate this agreement before the lease ends.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "high"


def test_termination_long_minimum_tenancy_is_medium_risk():
    comp = _make_comparison(
        "termination",
        "Minimum tenancy of 24 months shall apply.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "medium"
    assert any("24" in r for r in a.risk_reasons)


def test_termination_standard_text_is_low_risk():
    comp = _make_comparison(
        "termination",
        "Either party may terminate with 2 months written notice after the first 12 months.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "low"


# ---------------------------------------------------------------------------
# Repairs
# ---------------------------------------------------------------------------

def test_repairs_all_repairs_is_high_risk():
    comp = _make_comparison(
        "repairs",
        "The tenant shall be responsible for all repairs and maintenance.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "high"


def test_repairs_with_fair_wear_and_tear_is_low_risk():
    comp = _make_comparison(
        "repairs",
        "Tenant shall maintain the premises subject to fair wear and tear.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "low"
    assert any("wear and tear" in r.lower() for r in a.risk_reasons)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def test_utilities_all_no_cap_is_medium_risk():
    comp = _make_comparison(
        "utilities",
        "Tenant shall pay all utilities.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "medium"


def test_utilities_with_cap_is_low_risk():
    comp = _make_comparison(
        "utilities",
        "Tenant shall pay all utilities up to S$500 per month.",
    )

    a = assess_clause_risk(comp)

    assert a.severity == "low"


# ---------------------------------------------------------------------------
# Semantic deviation signal
# ---------------------------------------------------------------------------

def test_low_similarity_adds_medium_warning():
    """语义相似度极低时应该加 medium 级警告(即使其他条款看起来 ok)。"""
    comp = _make_comparison(
        "deposit",
        "Security deposit shall be 2 months rent.",
        similarity=0.05,  # 远低于 0.15 阈值
    )

    a = assess_clause_risk(comp)

    assert a.severity == "medium"  # 升级了
    assert any("semantically distant" in r for r in a.risk_reasons)


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

def test_summary_picks_worst_of_each_type():
    """同 type 多条 comparison 时,汇总应该取最严重的那条。"""
    comparisons = [
        _make_comparison("deposit", "2 months security deposit."),  # low
        _make_comparison("deposit", "6 months rent as deposit."),   # high
    ]

    summary = summarize_contract_risk(comparisons)

    deposit_assessments = [a for a in summary.assessments if a.clause_type == "deposit"]
    assert len(deposit_assessments) == 1  # 同 type 合并
    assert deposit_assessments[0].severity == "high"


def test_summary_high_overall_for_clean_contract():
    """4 类全是低风险 → overall low。"""
    comparisons = [
        _make_comparison("deposit", "2 months security deposit."),
        _make_comparison("termination", "Either party may terminate with 2 months notice after 12 months."),
        _make_comparison("repairs", "Tenant maintain premises subject to fair wear and tear."),
        _make_comparison("utilities", "Tenant pays utilities up to S$300/month."),
    ]

    summary = summarize_contract_risk(comparisons)

    assert summary.overall_level == "low"
    assert summary.overall_score >= 70
    assert summary.missing_clause_types == []


def test_summary_low_overall_for_problematic_contract():
    """高风险条款 + 缺失 → overall high。"""
    comparisons = [
        _make_comparison("deposit", "6 months rent as deposit."),  # high
        _make_comparison("termination", "Non-cancellable agreement."),  # high
        # 没有 repairs / utilities clause
    ]

    summary = summarize_contract_risk(comparisons)

    assert summary.overall_level in {"medium", "high"}
    assert "repairs" in summary.missing_clause_types
    assert "utilities" in summary.missing_clause_types


def test_summary_empty_comparisons():
    summary = summarize_contract_risk([])

    assert summary.assessments == []
    assert set(summary.missing_clause_types) == {"deposit", "termination", "repairs", "utilities"}
    assert summary.overall_level == "unknown"


def test_summary_uses_provided_extracted_clauses_for_missing_check():
    """传 extracted_clauses 应该走它的 missing 检查,而不是从 comparisons 反推。"""
    comparisons = [_make_comparison("deposit", "2 months deposit.")]
    # 4 类全部都"被识别"过(传完整 list)
    extracted = [
        _make_clause(t, "...")
        for t in ("deposit", "termination", "repairs", "utilities")
    ]

    summary = summarize_contract_risk(comparisons, extracted_clauses=extracted)

    assert summary.missing_clause_types == []


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------

def test_assessment_has_all_required_fields():
    comp = _make_comparison("deposit", "2 months security deposit.")
    a = assess_clause_risk(comp)

    assert isinstance(a, ClauseRiskAssessment)
    assert a.clause_type == "deposit"
    assert a.severity in {"low", "medium", "high"}
    assert 0.0 <= a.score <= 100.0
    assert isinstance(a.risk_reasons, list)
    assert a.sample_snippet
    assert a.cea_source


def test_summary_has_all_required_fields():
    comparisons = [_make_comparison("deposit", "2 months deposit.")]
    summary = summarize_contract_risk(comparisons)

    assert isinstance(summary, ContractRiskSummary)
    assert 0.0 <= summary.overall_score <= 100.0
    assert summary.overall_level in {"low", "medium", "high", "unknown"}
    assert isinstance(summary.assessments, list)
    assert isinstance(summary.missing_clause_types, list)
    assert summary.overall_reasons
