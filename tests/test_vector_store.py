"""ContractKnowledgeBase tests — B.

用 ephemeral (内存) Chroma + 单个 CEA PDF 保速度 (~5-15 秒首次会下载 embedding 模型)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.vector_store import (
    CEA_COLLECTION_NAME,
    ContractKnowledgeBase,
    SearchResult,
    seed_from_cea_templates,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cea_standard_lease"
HDB_TEMPLATE = DATA_DIR / "Tenancy Agreement Template for HDB Flats.pdf"


@pytest.fixture(scope="module")
def kb_with_hdb() -> ContractKnowledgeBase:
    """单份 HDB 模板,模块级 fixture (一次 ingest 多个测试共用,省时间)。"""
    kb = ContractKnowledgeBase(persist_dir=None)  # ephemeral
    chunks = kb.ingest_pdf(HDB_TEMPLATE, doc_id="hdb_template")
    assert chunks > 0
    return kb


def test_empty_kb_search_returns_empty():
    kb = ContractKnowledgeBase(
        collection_name="test_empty_isolated",
        persist_dir=None,
    )

    results = kb.search("deposit")

    assert results == []


def test_ingest_returns_positive_chunk_count(kb_with_hdb: ContractKnowledgeBase):
    stats = kb_with_hdb.stats()

    assert stats["chunk_count"] > 0
    assert stats["collection"] == CEA_COLLECTION_NAME


def test_search_finds_deposit_clause(kb_with_hdb: ContractKnowledgeBase):
    results = kb_with_hdb.search("security deposit amount", k=3)

    assert len(results) > 0
    assert all(isinstance(r, SearchResult) for r in results)
    # top-1 应该跟押金有点关系 — HDB 模板里押金条款是核心内容之一
    top_text_lower = results[0].text.lower()
    assert any(keyword in top_text_lower for keyword in ["deposit", "rent", "month", "tenant"])


def test_search_results_have_metadata(kb_with_hdb: ContractKnowledgeBase):
    results = kb_with_hdb.search("termination")

    assert len(results) > 0
    first = results[0]
    assert first.document == "hdb_template"
    assert first.page > 0
    assert first.score >= 0.0


def test_search_respects_k_parameter(kb_with_hdb: ContractKnowledgeBase):
    results_k2 = kb_with_hdb.search("rent", k=2)
    results_k5 = kb_with_hdb.search("rent", k=5)

    assert len(results_k2) <= 2
    assert len(results_k5) <= 5
    assert len(results_k5) >= len(results_k2)


def test_empty_query_returns_empty(kb_with_hdb: ContractKnowledgeBase):
    assert kb_with_hdb.search("") == []
    assert kb_with_hdb.search("   ") == []


def test_re_ingest_same_pdf_does_not_duplicate(kb_with_hdb: ContractKnowledgeBase):
    initial_count = kb_with_hdb.stats()["chunk_count"]

    # 重复 ingest 同一份 (upsert 应该不增加总数)
    kb_with_hdb.ingest_pdf(HDB_TEMPLATE, doc_id="hdb_template")

    after_count = kb_with_hdb.stats()["chunk_count"]
    assert after_count == initial_count


def test_seed_skips_when_collection_not_empty(kb_with_hdb: ContractKnowledgeBase):
    # 已经有内容了,seed 应该跳过 (除非 force=True)
    added = seed_from_cea_templates(kb=kb_with_hdb)

    assert added == 0


def test_ingest_missing_pdf_returns_zero():
    # 用独立 collection 名,避免跟其他测试共用进程级 ephemeral 状态
    kb = ContractKnowledgeBase(
        collection_name="test_missing_pdf_isolated",
        persist_dir=None,
    )

    chunks = kb.ingest_pdf("does/not/exist.pdf")

    assert chunks == 0
    assert kb.stats()["chunk_count"] == 0
