"""Contract risk scoring — B.

把 commit 2 的 ClauseComparison 转成用户能读懂的风险报告。

两层评分:
1. 语义相似度: commit 2 已算 (低相似度 = 跟 CEA 标准差异大,可疑)
2. 模式检测: regex 抓常见"陷阱条款"(4+ 个月押金 / 不可提前终止 /
   所有维修租客自付 / 无封顶水电)

输出:
- 每条 clause 的 ClauseRiskAssessment (severity + reasons + score)
- 整份合同的 ContractRiskSummary (overall_score + overall_level + missing_types)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from agents.contract_clauses import (
    Clause,
    ClauseType,
    found_clause_types,
    missing_clause_types,
)
from agents.contract_compare import ClauseComparison

Severity = Literal["low", "medium", "high"]
RiskLevel = Literal["low", "medium", "high", "unknown"]


@dataclass(frozen=True)
class ClauseRiskAssessment:
    """单条条款的风险评估。"""

    clause_type: ClauseType
    severity: Severity
    score: float  # 0-100, 越高越安全
    risk_reasons: list[str]  # "为什么这么评" 给用户看
    sample_snippet: str  # 原合同里的片段 (前 300 字符)
    cea_reference_snippet: str  # 最相似的 CEA 参考 (前 300 字符)
    cea_source: str  # 哪份 CEA 文件 + 第几页
    similarity: float


@dataclass(frozen=True)
class ContractRiskSummary:
    """整份合同的风险汇总。"""

    overall_score: float  # 0-100
    overall_level: RiskLevel
    assessments: list[ClauseRiskAssessment]
    missing_clause_types: list[ClauseType]  # 完全没在合同里出现的类型
    overall_reasons: list[str]  # 给用户的总结性说明


# ---------------------------------------------------------------------------
# 阈值常量
# ---------------------------------------------------------------------------

# 低于这个相似度认为合同条款"完全偏离" CEA 标准
SEMANTIC_DEVIATION_THRESHOLD = 0.15

# CEA 标准押金通常 1-3 个月
DEPOSIT_MONTHS_STANDARD_MAX = 3
DEPOSIT_MONTHS_HIGH_RISK = 5

# severity → score 映射
SEVERITY_BASE_SCORE = {"low": 90, "medium": 60, "high": 25}

# severity 排序 (合并多个 reason 时取最严重)
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


# ---------------------------------------------------------------------------
# Regex 模式
# ---------------------------------------------------------------------------

# "4 months", "24 months", "two months" 之类的月数
_MONTH_PATTERN = re.compile(
    r"(\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b|\b(\d{1,3})\b)\s*(?:month|months)",
    re.IGNORECASE,
)

_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _extract_month_counts(text: str) -> list[int]:
    """从条款文本里抽出所有"X 个月"的数字。"""
    counts: list[int] = []
    for match in _MONTH_PATTERN.finditer(text):
        word_match = match.group(1)
        if word_match and word_match.lower() in _WORD_TO_NUM:
            counts.append(_WORD_TO_NUM[word_match.lower()])
        else:
            try:
                counts.append(int(match.group(2) or match.group(1)))
            except (TypeError, ValueError):
                continue
    return counts


def _max_severity(severities: list[Severity]) -> Severity:
    """从一组 severity 里取最严重的。"""
    if not severities:
        return "low"
    return max(severities, key=lambda s: SEVERITY_RANK[s])


# ---------------------------------------------------------------------------
# 各 clause type 的具体风险检测
# ---------------------------------------------------------------------------

def _assess_deposit_risk(snippet: str) -> tuple[Severity, list[str]]:
    """押金条款: 看几个月。CEA 标准 1-3 个月。"""
    months = _extract_month_counts(snippet)
    if not months:
        return ("low", [])

    max_months = max(months)
    if max_months <= DEPOSIT_MONTHS_STANDARD_MAX:
        return ("low", [f"Deposit appears to be {max_months} month(s), within CEA norm of 1-3 months."])
    if max_months < DEPOSIT_MONTHS_HIGH_RISK:
        return (
            "medium",
            [
                f"Deposit of {max_months} months exceeds CEA norm of 1-3 months. "
                "Negotiate down to 2 months if possible."
            ],
        )
    return (
        "high",
        [
            f"Deposit of {max_months} months is significantly above CEA norm (1-3 months). "
            "This is a major financial commitment — strongly negotiate or walk away."
        ],
    )


def _assess_termination_risk(snippet: str) -> tuple[Severity, list[str]]:
    """提前终止条款: 看是否禁止 / 高罚金 / 长强制期。"""
    reasons: list[str] = []
    severities: list[Severity] = []
    lower = snippet.lower()

    if any(phrase in lower for phrase in ("non-cancellable", "non cancellable", "irrevocable")):
        severities.append("high")
        reasons.append(
            "Contract is marked non-cancellable / irrevocable — tenant cannot exit early. "
            "This is highly unusual and severely limits tenant flexibility."
        )

    if "no early termination" in lower or "shall not terminate" in lower:
        severities.append("high")
        reasons.append(
            "Clause prohibits early termination. CEA standard typically allows "
            "diplomatic clause or break clause after a minimum period."
        )

    # 强制最低租期 > 12 个月
    if "minimum tenancy" in lower or "minimum term" in lower:
        months = _extract_month_counts(snippet)
        if months and max(months) > 12:
            severities.append("medium")
            reasons.append(
                f"Minimum tenancy of {max(months)} months locks tenant in. "
                "CEA standard is typically 12 months."
            )

    if not severities:
        return ("low", ["Termination terms appear standard."])
    return (_max_severity(severities), reasons)


def _assess_repairs_risk(snippet: str) -> tuple[Severity, list[str]]:
    """维修条款: 看是否所有维修都租客负担。"""
    lower = snippet.lower()

    # 高危: 所有维修租客付
    high_risk_phrases = [
        "all repairs",
        "all maintenance",
        "tenant shall be responsible for all",
        "responsible for the repair of all",
    ]
    if any(phrase in lower for phrase in high_risk_phrases):
        return (
            "high",
            [
                "Tenant is required to bear ALL repair costs. CEA standard splits "
                "responsibility (tenant: minor wear; landlord: major structural). "
                "This shifts unreasonable burden to tenant."
            ],
        )

    # 中危: 排除 wear and tear
    if "fair wear and tear" not in lower and "wear and tear" in lower:
        if "exclud" in lower or "not includ" in lower:
            return (
                "medium",
                [
                    'Standard "fair wear and tear" exception appears excluded — '
                    "tenant may be charged for normal aging."
                ],
            )

    # 低危: 看到 fair wear and tear 是好信号
    if "fair wear and tear" in lower:
        return (
            "low",
            ['Includes standard "fair wear and tear" exception — tenant protected from normal aging charges.'],
        )

    return ("low", ["Repair terms appear within standard range."])


def _assess_utilities_risk(snippet: str) -> tuple[Severity, list[str]]:
    """水电费条款: 看是否所有杂费都租客出 / 是否有封顶。"""
    lower = snippet.lower()

    # 中危: 所有 utility 租客付且无封顶 (包括偏门项目如 cable / internet 也算进去)
    catch_all_phrases = [
        "all utilities",
        "all bills",
        "all charges",
    ]
    if any(phrase in lower for phrase in catch_all_phrases):
        # 如果有封顶则降级
        if "up to" in lower or "subject to" in lower or "capped" in lower:
            return (
                "low",
                ['"All utilities" clause has a cap mentioned — tenant exposure limited.'],
            )
        return (
            "medium",
            [
                'Tenant pays "all utilities" without an explicit cap. '
                "Confirm what's included (water/electricity/gas/internet/management fees) "
                "and whether any items are split or capped."
            ],
        )

    return ("low", ["Utilities terms appear within standard range."])


_ASSESSORS = {
    "deposit": _assess_deposit_risk,
    "termination": _assess_termination_risk,
    "repairs": _assess_repairs_risk,
    "utilities": _assess_utilities_risk,
}


# ---------------------------------------------------------------------------
# 单条 clause 评估 (语义 + 模式 综合)
# ---------------------------------------------------------------------------

def assess_clause_risk(comparison: ClauseComparison) -> ClauseRiskAssessment:
    """综合语义相似度 + 模式检测,给一条 clause 打分。"""
    clause = comparison.clause
    pattern_severity, pattern_reasons = _ASSESSORS[clause.clause_type](clause.snippet)
    severities: list[Severity] = [pattern_severity]
    reasons: list[str] = list(pattern_reasons)

    # 语义偏离也算一个独立信号
    if comparison.similarity < SEMANTIC_DEVIATION_THRESHOLD:
        severities.append("medium")
        reasons.append(
            f"Clause text is semantically distant from CEA standard "
            f"(similarity {comparison.similarity:.2f}). May indicate unusual phrasing."
        )

    final_severity = _max_severity(severities)
    score = float(SEVERITY_BASE_SCORE[final_severity])

    return ClauseRiskAssessment(
        clause_type=clause.clause_type,
        severity=final_severity,
        score=score,
        risk_reasons=reasons,
        sample_snippet=clause.snippet[:300],
        cea_reference_snippet=comparison.cea_reference_snippet[:300],
        cea_source=f"{comparison.cea_source_document} p{comparison.cea_source_page}",
        similarity=comparison.similarity,
    )


# ---------------------------------------------------------------------------
# 整份合同汇总
# ---------------------------------------------------------------------------

# 每个缺失的 clause type 扣几分 (从 100 开始扣)
MISSING_CLAUSE_PENALTY = 15


def summarize_contract_risk(
    comparisons: list[ClauseComparison],
    extracted_clauses: list[Clause] | None = None,
) -> ContractRiskSummary:
    """把一份合同的所有 ClauseComparison 汇总成整体风险。

    Args:
        comparisons: commit 2 输出的 ClauseComparison 列表
        extracted_clauses: 可选, 用于检测 missing clause types (没有则推断)

    Returns:
        ContractRiskSummary, 含每条评估 + 整体评分。
    """
    # 1. 同 type 多个 comparison 时,优先取 severity 最高那条
    #    (用户看到最坏情况比看到平均更安全)
    assessments_by_type: dict[ClauseType, ClauseRiskAssessment] = {}
    for comp in comparisons:
        assessment = assess_clause_risk(comp)
        existing = assessments_by_type.get(assessment.clause_type)
        if existing is None or SEVERITY_RANK[assessment.severity] > SEVERITY_RANK[existing.severity]:
            assessments_by_type[assessment.clause_type] = assessment

    assessments = list(assessments_by_type.values())

    # 2. 缺失的 clause type
    if extracted_clauses is not None:
        missing = sorted(missing_clause_types(extracted_clauses))
    else:
        # 从 comparisons 反推
        present = {c.clause.clause_type for c in comparisons}
        missing = sorted({"deposit", "termination", "repairs", "utilities"} - present)

    # 3. 总分: 取所有 clause 评估分的均值, 每个缺失类型再扣分
    if assessments:
        avg_clause_score = sum(a.score for a in assessments) / len(assessments)
    else:
        avg_clause_score = 0.0
    overall_score = max(0.0, avg_clause_score - MISSING_CLAUSE_PENALTY * len(missing))

    # 4. risk_level 阈值
    # 没任何 assessment 才是 unknown (合同没解析到内容)
    # 有 assessment 即使总分被扣到 0 也是 high (有问题就是有问题)
    if not assessments:
        overall_level: RiskLevel = "unknown"
    elif overall_score >= 70:
        overall_level = "low"
    elif overall_score >= 45:
        overall_level = "medium"
    else:
        overall_level = "high"

    # 5. 总结 reasons
    overall_reasons: list[str] = []
    high_severity_types = [a.clause_type for a in assessments if a.severity == "high"]
    if high_severity_types:
        overall_reasons.append(
            f"High-severity issues found in: {', '.join(high_severity_types)}."
        )
    if missing:
        overall_reasons.append(
            f"No clause found for: {', '.join(missing)}. "
            f"Missing terms can leave tenant unprotected — request explicit clauses."
        )
    if not overall_reasons:
        overall_reasons.append("No major deviations from CEA standard detected.")

    return ContractRiskSummary(
        overall_score=round(overall_score, 1),
        overall_level=overall_level,
        assessments=sorted(assessments, key=lambda a: a.clause_type),
        missing_clause_types=missing,
        overall_reasons=overall_reasons,
    )


__all__ = [
    "ClauseRiskAssessment",
    "ContractRiskSummary",
    "RiskLevel",
    "Severity",
    "assess_clause_risk",
    "summarize_contract_risk",
]
