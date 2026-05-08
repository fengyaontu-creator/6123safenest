"""Contract clause vs CEA standard comparison — B.

把从合同抽取出来的 Clause 跟 CEA 标准租约知识库做语义对比,
返回每条 clause 最相似的 CEA 参考片段 + 相似度评分。

后续 commit 3 会基于这些 comparison 结果做风险评分。

策略:
- 对每个 Clause,用 vector_store.search 查 top-1 CEA 标准片段
- distance → similarity 的转换: similarity = 1 / (1 + distance)
- 不带主观判断,只做"匹配 + 度量",评分逻辑放后续 commit
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.contract_clauses import Clause, ClauseType
from config import settings
from tools.vector_store import ContractKnowledgeBase, seed_from_cea_templates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClauseComparison:
    """单条合同条款 vs CEA 标准的对比结果。"""

    clause: Clause
    cea_reference_snippet: str
    cea_source_document: str
    cea_source_page: int
    similarity: float  # 0-1, 越大越接近 CEA 标准
    raw_distance: float  # Chroma 原始距离, 越小越相似 (调试用)


# 没找到任何 CEA 参考时的占位
NO_REFERENCE_SNIPPET = ""
NO_REFERENCE_DOCUMENT = "<none>"


def _distance_to_similarity(distance: float) -> float:
    """Chroma 用 squared L2 距离, 转成 0-1 相似度方便阅读。"""
    if distance < 0:
        return 0.0
    return round(1.0 / (1.0 + distance), 3)


def _ensure_kb(kb: ContractKnowledgeBase | None) -> ContractKnowledgeBase:
    """没传 kb 就用默认持久化路径, 空集合自动 seed。"""
    if kb is not None:
        return kb

    kb = ContractKnowledgeBase(persist_dir=settings.chroma_persist_dir)
    if kb.stats()["chunk_count"] == 0:
        logger.info("Vector store empty, seeding from CEA templates (first run only)...")
        seed_from_cea_templates(kb=kb)
    return kb


def compare_clause_to_cea(
    clause: Clause,
    kb: ContractKnowledgeBase,
) -> ClauseComparison:
    """单条 clause 对 CEA 标准库做 top-1 检索。"""
    # 把关键词 + snippet 一起作为 query, 提高召回相关 CEA 段落的概率
    query = f"{clause.matched_keyword} {clause.snippet}".strip()
    results = kb.search(query, k=1)

    if not results:
        return ClauseComparison(
            clause=clause,
            cea_reference_snippet=NO_REFERENCE_SNIPPET,
            cea_source_document=NO_REFERENCE_DOCUMENT,
            cea_source_page=0,
            similarity=0.0,
            raw_distance=float("inf"),
        )

    top = results[0]
    return ClauseComparison(
        clause=clause,
        cea_reference_snippet=top.text,
        cea_source_document=top.document,
        cea_source_page=top.page,
        similarity=_distance_to_similarity(top.score),
        raw_distance=round(top.score, 3),
    )


def compare_to_cea_standard(
    clauses: list[Clause],
    kb: ContractKnowledgeBase | None = None,
) -> list[ClauseComparison]:
    """把抽取出的所有 clauses 跟 CEA 知识库逐条对比。

    Args:
        clauses: extract_clauses 输出的 Clause 列表
        kb: 知识库实例。为 None 时用默认持久化路径并自动 seed
            (首次跑会下载 embedding 模型,~30-60 秒;之后跳过)

    Returns:
        每条输入 clause 对应一条 ClauseComparison。
        没匹配到任何 CEA 参考时 similarity=0.0, document="<none>"。
    """
    if not clauses:
        return []

    kb = _ensure_kb(kb)
    return [compare_clause_to_cea(c, kb) for c in clauses]


def best_comparison_per_type(
    comparisons: list[ClauseComparison],
) -> dict[ClauseType, ClauseComparison]:
    """同 clause_type 多条命中时, 保留 similarity 最高的一条。

    给后续风险评分用——每个 type 通常只关心"最相似的那条 CEA 标准"。
    """
    best: dict[ClauseType, ClauseComparison] = {}
    for comp in comparisons:
        ctype = comp.clause.clause_type
        if ctype not in best or comp.similarity > best[ctype].similarity:
            best[ctype] = comp
    return best


__all__ = [
    "ClauseComparison",
    "best_comparison_per_type",
    "compare_clause_to_cea",
    "compare_to_cea_standard",
]
