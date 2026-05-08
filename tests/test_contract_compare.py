"""Contract compare tests — B.

用预先 seed 好的 ephemeral kb (一份 HDB CEA 模板) 跑全套,
避免每次测试都触发模型下载 + 全 5 PDF ingest。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.contract_clauses import Clause, extract_clauses
from agents.contract_compare import (
    ClauseComparison,
    best_comparison_per_type,
    compare_clause_to_cea,
    compare_to_cea_standard,
)
from tools.pdf_parser import extract_pages
from tools.vector_store import ContractKnowledgeBase

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cea_standard_lease"
HDB_TEMPLATE = DATA_DIR / "Tenancy Agreement Template for HDB Flats.pdf"


@pytest.fixture(scope="module")
def kb_seeded() -> ContractKnowledgeBase:
    """一份 HDB 模板进 ephemeral kb,模块级 fixture 共享避免重复 ingest。"""
    kb = ContractKnowledgeBase(
        collection_name="test_contract_compare_seeded",
        persist_dir=None,
    )
    chunks = kb.ingest_pdf(HDB_TEMPLATE, doc_id="hdb_template")
    assert chunks > 0
    return kb


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_clauses_returns_empty(kb_seeded: ContractKnowledgeBase):
    assert compare_to_cea_standard([], kb=kb_seeded) == []


# ---------------------------------------------------------------------------
# Single clause comparison
# ---------------------------------------------------------------------------

def test_deposit_clause_finds_cea_reference(kb_seeded: ContractKnowledgeBase):
    clause = Clause(
        clause_type="deposit",
        snippet="The tenant shall pay 4 months rent as security deposit upon signing.",
        source_page=1,
        method="keyword",
        confidence=0.7,
        matched_keyword="security deposit",
    )

    comp = compare_clause_to_cea(clause, kb_seeded)

    assert isinstance(comp, ClauseComparison)
    assert comp.cea_reference_snippet, "Should find some CEA reference"
    assert comp.cea_source_document == "hdb_template"
    assert comp.similarity > 0.0
    assert comp.raw_distance >= 0.0


def test_unrelated_clause_still_returns_a_match_with_low_similarity(
    kb_seeded: ContractKnowledgeBase,
):
    """完全无关的文本也会返回 top-1 (因为 KB 一直能给最相似的),
    但 similarity 应该比真合同条款低。"""
    deposit_clause = Clause(
        clause_type="deposit",
        snippet="Security deposit shall be 2 months rent.",
        source_page=1,
        method="keyword",
        confidence=0.7,
        matched_keyword="security deposit",
    )
    nonsense_clause = Clause(
        clause_type="deposit",
        snippet="Bananas pineapples elephants flying through outer space.",
        source_page=1,
        method="keyword",
        confidence=0.7,
        matched_keyword="security deposit",
    )

    deposit_comp = compare_clause_to_cea(deposit_clause, kb_seeded)
    nonsense_comp = compare_clause_to_cea(nonsense_clause, kb_seeded)

    assert deposit_comp.similarity > nonsense_comp.similarity


# ---------------------------------------------------------------------------
# Bulk comparison on real extracted clauses
# ---------------------------------------------------------------------------

def test_compare_real_extracted_clauses(kb_seeded: ContractKnowledgeBase):
    """跑真实 pipeline:HDB 模板抽 clauses → 跟 kb 对比"""
    pages = extract_pages(HDB_TEMPLATE)
    clauses = extract_clauses(pages)
    assert len(clauses) > 0

    comparisons = compare_to_cea_standard(clauses, kb=kb_seeded)

    assert len(comparisons) == len(clauses)
    # 因为 sample 就是 CEA 模板自己,所有 comparisons 都该高度相似
    avg_similarity = sum(c.similarity for c in comparisons) / len(comparisons)
    assert avg_similarity > 0.3, f"Avg similarity too low: {avg_similarity}"


def test_comparison_preserves_clause_metadata(kb_seeded: ContractKnowledgeBase):
    clause = Clause(
        clause_type="termination",
        snippet="Early termination requires 2 months notice.",
        source_page=5,
        method="keyword",
        confidence=0.7,
        matched_keyword="early termination",
    )

    comp = compare_clause_to_cea(clause, kb_seeded)

    # 原 clause 应该原封不动地保留在结果里
    assert comp.clause is clause
    assert comp.clause.clause_type == "termination"
    assert comp.clause.source_page == 5


# ---------------------------------------------------------------------------
# best_comparison_per_type
# ---------------------------------------------------------------------------

def test_best_comparison_keeps_highest_similarity_per_type(
    kb_seeded: ContractKnowledgeBase,
):
    pages = extract_pages(HDB_TEMPLATE)
    clauses = extract_clauses(pages)
    comparisons = compare_to_cea_standard(clauses, kb=kb_seeded)

    best = best_comparison_per_type(comparisons)

    # 每个 type 只保留一条
    types_seen = set(best.keys())
    assert types_seen.issubset({"deposit", "termination", "repairs", "utilities"})

    # 每个被选中的 best 在该 type 内应该是相似度最高的
    for ctype, best_comp in best.items():
        same_type_all = [c for c in comparisons if c.clause.clause_type == ctype]
        max_sim = max(c.similarity for c in same_type_all)
        assert best_comp.similarity == max_sim


def test_best_comparison_handles_empty():
    assert best_comparison_per_type([]) == {}


# ---------------------------------------------------------------------------
# Empty kb behavior
# ---------------------------------------------------------------------------

def test_empty_kb_returns_no_reference():
    empty_kb = ContractKnowledgeBase(
        collection_name="test_compare_empty_kb",
        persist_dir=None,
    )
    clause = Clause(
        clause_type="deposit",
        snippet="Security deposit clause text.",
        source_page=1,
        method="keyword",
        confidence=0.7,
        matched_keyword="security deposit",
    )

    comp = compare_clause_to_cea(clause, empty_kb)

    assert comp.cea_reference_snippet == ""
    assert comp.cea_source_document == "<none>"
    assert comp.similarity == 0.0
