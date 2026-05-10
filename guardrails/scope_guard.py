"""Out-of-scope refusal — blocks queries that fall outside SafeNest's
rental-assessment domain (legal advice, immigration, financial guarantees,
medical advice, discrimination, NSFW).

15 patterns across 6 categories.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class _ScopePattern(NamedTuple):
    pattern: re.Pattern[str]
    category: str


# ── 15 out-of-scope patterns ──────────────────────────────────────────────
_PATTERNS: list[_ScopePattern] = [
    # ── legal_advice / legal_action ───────────────────────────────────────
    _ScopePattern(re.compile(r"\b(sue|file\s+a\s+lawsuit|take\s+legal\s+action)\b", re.I),
                  "legal_advice"),
    _ScopePattern(re.compile(r"\blegal\s+advice\b", re.I),
                  "legal_advice"),
    _ScopePattern(re.compile(r"\bdraft\s+(a|the)\s+(legal|cease|demand|formal)\s+(document|letter|notice)", re.I),
                  "legal_advice"),
    _ScopePattern(re.compile(r"\brepresent\s+(me|myself)\s+in\s+(court|tribunal|hearing)", re.I),
                  "legal_advice"),
    _ScopePattern(re.compile(r"\b(lawyer|attorney|barrister|solicitor)\b", re.I),
                  "legal_advice"),

    # ── immigration_advice ────────────────────────────────────────────────
    _ScopePattern(re.compile(r"\b(apply|how\s+to\s+(get|obtain|apply))\s+(for\s+)?(a\s+|an\s+)?(PR|permanent\s+residen|visa|S.?Pass|E.?Pass|work\s+permit)", re.I),
                  "immigration_advice"),
    _ScopePattern(re.compile(r"\b(immigration|visa)\s+(application|status|approval|appeal)", re.I),
                  "immigration_advice"),
    _ScopePattern(re.compile(r"\b(permanent\s+residence?|long\s*term\s*visit\s*pass|LTVP|citizenship)", re.I),
                  "immigration_advice"),

    # ── financial_guarantee / advice ──────────────────────────────────────
    _ScopePattern(re.compile(r"\b(guarantee|guaranteed)\s+(100%|total|full|uncondition)\s+(approval|return|success)", re.I),
                  "financial_guarantee"),
    _ScopePattern(re.compile(r"\b(financial|investment|loan|mortgage)\s+advice\b", re.I),
                  "financial_guarantee"),
    _ScopePattern(re.compile(r"\b(predict|forecast)\s+(rental|property|market)\s+(price|trend)", re.I),
                  "financial_guarantee"),

    # ── medical_advice ────────────────────────────────────────────────────
    _ScopePattern(re.compile(r"\bmedical\s+(advice|condition|diagnosis|treatment)\b", re.I),
                  "medical_advice"),

    # ── discrimination ────────────────────────────────────────────────────
    _ScopePattern(re.compile(r"\b(no\s+(Indians?|Chinese|Malays|Filipinos?|foreigners?|PRs?)|discriminat)", re.I),
                  "discrimination"),

    # ── nsfw ──────────────────────────────────────────────────────────────
    _ScopePattern(re.compile(r"\b(nsfw|porn|escort|sexual)\b", re.I),
                  "nsfw"),
]

_CATEGORY_NAMES: dict[str, str] = {
    "legal_advice": "legal advice",
    "immigration_advice": "immigration advice",
    "financial_guarantee": "financial guarantee or investment advice",
    "medical_advice": "medical advice",
    "discrimination": "discrimination or hate speech",
    "nsfw": "inappropriate content",
}


SCOPE_REFUSAL_TEMPLATE = (
    "I'm sorry, but SafeNest is a Singapore rental assessment assistant. "
    "{reason} is outside my scope. "
    "For {topic}, please consult a qualified professional. "
    "I'm happy to help with rental price comparisons, contract clause checks, "
    "location assessments, and CEA agent verification — how can I assist?"
)


def check_scope(text: str) -> tuple[bool, str | None]:
    """Check whether *text* wanders outside SafeNest's rental domain.

    Returns
    -------
    (is_refused, reason)
        is_refused : ``True`` when any out-of-scope pattern matches.
        reason     : human-readable category of the first match, or ``None``.
    """
    if not text or not text.strip():
        return (False, None)

    for entry in _PATTERNS:
        if entry.pattern.search(text):
            cat = entry.category
            readable = _CATEGORY_NAMES.get(cat, cat)
            return (True, readable)

    return (False, None)


__all__ = ["check_scope", "SCOPE_REFUSAL_TEMPLATE"]
