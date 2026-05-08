"""Contract clause extraction tests — B."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.contract_clauses import (
    Clause,
    extract_clauses,
    found_clause_types,
    missing_clause_types,
)
from tools.pdf_parser import extract_pages

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cea_standard_lease"
HDB_TEMPLATE = DATA_DIR / "Tenancy Agreement Template for HDB Flats.pdf"
PRIVATE_TEMPLATE = DATA_DIR / "Tenancy Agreement Template for Private Residential Property.pdf"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_pages_returns_empty():
    assert extract_clauses([]) == []


def test_unrelated_text_returns_empty():
    pages = ["This is just some random text about cats and weather, nothing about renting."]

    clauses = extract_clauses(pages)

    assert clauses == []


def test_single_clause_in_single_page():
    pages = [
        "Section 5. SECURITY DEPOSIT. The tenant shall pay an amount equivalent "
        "to two months rent as security deposit upon signing this agreement."
    ]

    clauses = extract_clauses(pages)

    assert len(clauses) >= 1
    assert any(c.clause_type == "deposit" for c in clauses)
    deposit = next(c for c in clauses if c.clause_type == "deposit")
    assert "security deposit" in deposit.snippet.lower()
    assert deposit.source_page == 1


# ---------------------------------------------------------------------------
# Real CEA standard lease — must find all 4 clause types
# ---------------------------------------------------------------------------

def test_hdb_template_finds_all_four_clause_types():
    pages = extract_pages(HDB_TEMPLATE)
    assert pages, "HDB template should extract text"

    clauses = extract_clauses(pages)
    found = found_clause_types(clauses)

    # CEA HDB 标准租约必然涵盖 4 类
    assert "deposit" in found, f"deposit not found, got: {found}"
    assert "termination" in found, f"termination not found, got: {found}"
    assert "repairs" in found, f"repairs not found, got: {found}"
    assert "utilities" in found, f"utilities not found, got: {found}"

    # 至少 4 条,通常更多(同类多次出现)
    assert len(clauses) >= 4


def test_private_template_finds_all_four_clause_types():
    pages = extract_pages(PRIVATE_TEMPLATE)

    clauses = extract_clauses(pages)
    found = found_clause_types(clauses)

    expected = {"deposit", "termination", "repairs", "utilities"}
    missing = expected - found
    assert not missing, f"Private template missing clause types: {missing}"


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------

def test_clause_has_required_fields():
    pages = extract_pages(HDB_TEMPLATE)
    clauses = extract_clauses(pages)

    assert all(isinstance(c, Clause) for c in clauses)
    for c in clauses:
        assert c.clause_type in {"deposit", "termination", "repairs", "utilities"}
        assert c.snippet, "snippet should not be empty"
        assert c.source_page > 0
        assert c.method == "keyword"
        assert 0.0 <= c.confidence <= 1.0
        assert c.matched_keyword, "matched_keyword should not be empty"


def test_snippet_contains_context_around_match():
    """Snippet 应该包含命中点前后的上下文,不只是关键词本身。"""
    pages = ["Lorem ipsum dolor sit amet, the security deposit is one month rent, consectetur adipiscing elit, sed do eiusmod tempor."]

    clauses = extract_clauses(pages)

    assert clauses
    snippet = clauses[0].snippet
    assert len(snippet) > len("security deposit")
    assert "lorem" in snippet.lower() or "consectetur" in snippet.lower()


# ---------------------------------------------------------------------------
# Multi-page handling
# ---------------------------------------------------------------------------

def test_clauses_on_different_pages_are_returned_separately():
    pages = [
        "Page 1: We will discuss the security deposit later in this agreement.",
        "Page 2: The early termination clause requires 2 months notice.",
        "Page 3: All utility bills shall be paid by the tenant.",
    ]

    clauses = extract_clauses(pages)
    pages_with_hits = {c.source_page for c in clauses}

    assert 1 in pages_with_hits
    assert 2 in pages_with_hits
    assert 3 in pages_with_hits


def test_nearby_duplicate_keywords_are_merged():
    """同页同类型且位置接近的命中应该合并成一条。"""
    # 同一句话里 "security deposit" 和 "deposit shall" 都命中 deposit 类
    pages = [
        "The security deposit shall be 2 months rent. The deposit shall be returned within 14 days."
    ]

    clauses = extract_clauses(pages)
    deposit_clauses = [c for c in clauses if c.clause_type == "deposit"]

    # 两次命中位置接近,应该合并成 1 条而不是 2 条
    assert len(deposit_clauses) == 1


def test_distant_same_type_clauses_kept_separate():
    """同页同类型但距离远的两次命中应该保留为两条。"""
    distant_text = (
        "The security deposit clause is here. "
        + ("padding text. " * 50)  # 拉开距离
        + "Another mention of deposit shall be relevant later."
    )
    pages = [distant_text]

    clauses = extract_clauses(pages)
    deposit_clauses = [c for c in clauses if c.clause_type == "deposit"]

    assert len(deposit_clauses) == 2


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def test_missing_clause_types_when_only_two_present():
    pages = [
        "The security deposit is 2 months rent. "
        "Termination of this agreement requires 2 months notice."
    ]

    clauses = extract_clauses(pages)

    found = found_clause_types(clauses)
    missing = missing_clause_types(clauses)

    assert "deposit" in found
    assert "termination" in found
    assert "repairs" in missing
    assert "utilities" in missing


def test_missing_clause_types_when_all_present():
    """完整合同应该没有缺失的类型。"""
    pages = extract_pages(HDB_TEMPLATE)
    clauses = extract_clauses(pages)

    assert missing_clause_types(clauses) == set()


def test_found_and_missing_partition_correctly():
    """found 和 missing 应该是 4 类的完整划分(不重不漏)。"""
    pages = ["Just the security deposit clause and nothing else relevant."]
    clauses = extract_clauses(pages)

    found = found_clause_types(clauses)
    missing = missing_clause_types(clauses)

    assert found.isdisjoint(missing)
    assert found | missing == {"deposit", "termination", "repairs", "utilities"}
