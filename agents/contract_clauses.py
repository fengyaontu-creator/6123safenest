"""Contract clause extraction — B.

从合同文本里抽取 4 类核心条款,Contract Agent 用它做后续的 CEA 标准对比 + 风险评分。

策略:
- 关键词匹配(快、确定性、不依赖 LLM、可单元测试)
- 按页搜索,匹配上抽 200 字符上下文
- 同类型多次命中按位置去重
- 后续 commit 会加 LLM-based 增强(本 commit 只做关键词版)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ClauseType = Literal["deposit", "termination", "repairs", "utilities"]

# 各类条款的英文关键词。基于 CEA 标准租约 + 常见合同用语整理。
# 关键词按"短语优先级 / 特异性"排序——更具体的关键词先匹配,提高 confidence。
CLAUSE_KEYWORDS: dict[ClauseType, list[str]] = {
    "deposit": [
        "security deposit",
        "advance rental",
        "rental deposit",
        "deposit shall",
        "deposit of",
        "month's rent as deposit",
    ],
    "termination": [
        "early termination",
        "diplomatic clause",
        "break clause",
        "terminate this agreement",
        "termination of this",
        "may terminate",
    ],
    "repairs": [
        "fair wear and tear",
        "wear and tear",
        "tenant shall maintain",
        "tenant shall repair",
        "landlord shall repair",
        "responsible for the repair",
        "minor repairs",
    ],
    "utilities": [
        "utility bills",
        "utility charges",
        "utilities account",
        "supply of water",
        "water, electricity",
        "water and electricity",
        "electricity bill",
        "payment of rent and utilities",
        # 单词级兜底——CEA 标准租约把 "Utilities" 用作标题
        "utilities",
    ],
}

# 抽取窗口大小: 命中点前后各 N 个字符
CONTEXT_WINDOW_CHARS = 200

# 同类型的两次命中如果距离很近,合并为一条
MERGE_NEARBY_THRESHOLD_CHARS = 100


@dataclass(frozen=True)
class Clause:
    """单个抽取到的合同条款。"""

    clause_type: ClauseType
    snippet: str
    source_page: int
    method: str = "keyword"
    confidence: float = 0.7
    matched_keyword: str = ""


@dataclass
class _RawHit:
    """抽取过程的中间结果,合并去重前用。"""

    clause_type: ClauseType
    page: int
    start: int
    end: int
    matched_keyword: str

    snippet: str = ""


def _normalize_text(text: str) -> str:
    """把多重空白(换行 / 多空格)压缩成单空格,方便跨行匹配关键词。"""
    return re.sub(r"\s+", " ", text)


def _extract_window(text: str, hit_start: int, hit_end: int) -> str:
    window_start = max(0, hit_start - CONTEXT_WINDOW_CHARS)
    window_end = min(len(text), hit_end + CONTEXT_WINDOW_CHARS)
    snippet = text[window_start:window_end].strip()
    # 把内部多重空白也压一下,避免输出杂乱
    return re.sub(r"\s+", " ", snippet)


def _find_hits_on_page(page_text: str, page_num: int) -> list[_RawHit]:
    """单页里搜所有 4 类关键词,返回原始命中列表。"""
    if not page_text:
        return []

    normalized = _normalize_text(page_text)
    lower = normalized.lower()
    hits: list[_RawHit] = []

    for clause_type, keywords in CLAUSE_KEYWORDS.items():
        for keyword in keywords:
            kw_lower = keyword.lower()
            search_start = 0
            while True:
                idx = lower.find(kw_lower, search_start)
                if idx == -1:
                    break
                hit = _RawHit(
                    clause_type=clause_type,
                    page=page_num,
                    start=idx,
                    end=idx + len(kw_lower),
                    matched_keyword=keyword,
                    snippet=_extract_window(normalized, idx, idx + len(kw_lower)),
                )
                hits.append(hit)
                search_start = idx + len(kw_lower)

    return hits


def _dedupe_and_merge(hits: list[_RawHit]) -> list[_RawHit]:
    """同页 / 同类型 / 位置接近的命中合并成一条,避免输出冗余。"""
    if not hits:
        return []

    # 按 (clause_type, page, start) 排序便于线性合并
    hits_sorted = sorted(hits, key=lambda h: (h.clause_type, h.page, h.start))

    merged: list[_RawHit] = []
    for hit in hits_sorted:
        if not merged:
            merged.append(hit)
            continue

        last = merged[-1]
        same_type_and_page = last.clause_type == hit.clause_type and last.page == hit.page
        nearby = (hit.start - last.end) <= MERGE_NEARBY_THRESHOLD_CHARS

        if same_type_and_page and nearby:
            # 合并: 扩展 snippet 范围,保留先匹配的关键词作为代表
            continue
        merged.append(hit)

    return merged


def extract_clauses(pages: list[str]) -> list[Clause]:
    """从按页切分的合同文本里抽取所有 4 类条款。

    Args:
        pages: 每页一个字符串的列表(通常来自 ``tools.pdf_parser.extract_pages``)。

    Returns:
        按 (clause_type, page) 排序的 Clause 列表。每条 clause 含 200 字符上下文。
    """
    if not pages:
        return []

    all_hits: list[_RawHit] = []
    for page_num, page_text in enumerate(pages, start=1):
        all_hits.extend(_find_hits_on_page(page_text, page_num))

    merged = _dedupe_and_merge(all_hits)

    return [
        Clause(
            clause_type=hit.clause_type,
            snippet=hit.snippet,
            source_page=hit.page,
            method="keyword",
            confidence=0.7,
            matched_keyword=hit.matched_keyword,
        )
        for hit in merged
    ]


def found_clause_types(clauses: list[Clause]) -> set[ClauseType]:
    """从 Clause 列表里提取已识别的 type 集合,用来检查"哪些类没找到"。"""
    return {c.clause_type for c in clauses}


def missing_clause_types(clauses: list[Clause]) -> set[ClauseType]:
    """返回 4 类里未识别的——后续风险分析的输入(没找到等于"未约定")。"""
    expected: set[ClauseType] = {"deposit", "termination", "repairs", "utilities"}
    return expected - found_clause_types(clauses)


__all__ = [
    "CLAUSE_KEYWORDS",
    "Clause",
    "ClauseType",
    "extract_clauses",
    "found_clause_types",
    "missing_clause_types",
]
