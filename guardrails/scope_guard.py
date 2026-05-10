"""Scope guard — B.

Refuses queries outside SafeNest's rental-screening scope (legal advice,
immigration, financial guarantees, medical advice, discrimination, NSFW).
Returns refusal info on hit or None on pass.
"""

from __future__ import annotations

import re
from typing import Optional

SCOPE_REFUSAL_TEMPLATE = (
    "SafeNest can only help with Singapore rental screening — comparing rent, "
    "verifying CEA-registered agents, flagging contract risks, and assessing "
    "location convenience. For {topic}, please consult a qualified professional "
    "or the appropriate government agency."
)

_LEGAL = [
    r"\b(?:legal\s+advice|legal\s+opinion)\b",
    r"\bsue\s+(?:my|the)\s+\w+",
    r"\bdraft\s+(?:a|an|the)?\s*legal\b",
    # Only catch when user is requesting a lawyer's services, not just mentioning the profession.
    r"\b(?:need|want|hire|find|get|consult|recommend|talk\s+to|see)\s+(?:a\s+|an\s+)?(?:lawyer|attorney|solicitor)\b",
    r"\blawsuit\b",
]

_IMMIGRATION = [
    r"\bapply\s+for\s+(?:a\s+|the\s+)?(?:PR|permanent\s+resident|EP|S\s*Pass|work\s+permit)\b",
    r"\b(?:visa|immigration)\s+(?:advice|application|status|process)\b",
    r"\bICA\s+(?:application|appeal)\b",
]

_FINANCIAL = [
    r"\bguarantee\s+(?:100%|approval|success)",
    r"\bfinancial\s+(?:advice|planning|guarantee)\b",
    r"\b(?:loan|mortgage)\s+approval\b",
]

_MEDICAL = [
    r"\bmedical\s+advice\b",
]

_DISCRIMINATION = [
    r"\b(?:only|prefer|reject|exclude)\s+(?:chinese|malay|indian|eurasian|foreigners?|locals?|men|women|muslims?|christians?)\b",
]

_NSFW = [
    r"\b(?:sexual|nsfw|porn|escort)\b",
]

_TOPIC_LABELS: dict[str, str] = {
    "legal_advice": "legal matters",
    "immigration_advice": "immigration matters",
    "financial_guarantee": "financial matters",
    "medical_advice": "medical matters",
    "discrimination": "discriminatory requests",
    "nsfw": "non-rental adult content",
}

_PATTERNS_BY_CATEGORY: dict[str, list[str]] = {
    "legal_advice": _LEGAL,
    "immigration_advice": _IMMIGRATION,
    "financial_guarantee": _FINANCIAL,
    "medical_advice": _MEDICAL,
    "discrimination": _DISCRIMINATION,
    "nsfw": _NSFW,
}

_COMPILED: list[tuple[str, re.Pattern[str]]] = [
    (category, re.compile(pattern, re.IGNORECASE))
    for category, patterns in _PATTERNS_BY_CATEGORY.items()
    for pattern in patterns
]


def check_scope(text: Optional[str]) -> Optional[dict]:
    """Return refusal info if `text` is out-of-scope, else None.

    Empty/None input passes (orchestrator will ask for clarification anyway).
    """

    if not text or not text.strip():
        return None

    for category, regex in _COMPILED:
        match = regex.search(text)
        if match:
            topic = _TOPIC_LABELS.get(category, category)
            return {
                "refused": True,
                "category": category,
                "pattern": regex.pattern,
                "match": match.group(0),
                "message": SCOPE_REFUSAL_TEMPLATE.format(topic=topic),
            }
    return None


__all__ = [
    "SCOPE_REFUSAL_TEMPLATE",
    "check_scope",
]
