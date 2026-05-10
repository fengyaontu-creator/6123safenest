"""Prompt-injection filter — detects and blocks prompt injection attacks via regex.

Covers 17 patterns across 6 categories:
  - instruction_override (5): ignore / forget / override / disregard instructions
  - prompt_extraction (3):   steal system prompt / reveal rules
  - token_injection (1):     special token markers like <|im_start|>
  - jailbreak (4):           DAN / jailbreak / bypass / pretend
  - role_play (3):           pretend to be hacker / criminal / unethical
  - format_manipulation (2): control output format / suppress warnings
"""

from __future__ import annotations

import re
from typing import NamedTuple


class _Pattern(NamedTuple):
    """A single detection pattern with regex, category label, and risk weight."""

    pattern: re.Pattern[str]
    category: str
    weight: float


# Threshold above which a match is considered an injection attack.
_BLOCK_THRESHOLD = 0.7

# ---------------------------------------------------------------------------
# 17 detection patterns
# ---------------------------------------------------------------------------
_PATTERNS: list[_Pattern] = [
    # ── instruction_override ──────────────────────────────────────────────
    _Pattern(re.compile(r"ignore\s+(?:(?:all|previous|your|the|every)\s+)*(instructions?|prompts?|rules?|guidelines?|directives?)", re.I),
             "instruction_override", 0.9),
    _Pattern(re.compile(r"forget\s+(everything|all|what|you\s+know|you\s+are|your)\s+(?:about\s+)?(?:your\s+)?(instructions?|prompts?|rules?|training|programming)?", re.I),
             "instruction_override", 0.8),
    _Pattern(re.compile(r"you\s+are\s+(now|no\s+longer)\s+a", re.I),
             "instruction_override", 0.7),
    _Pattern(re.compile(r"override\s+(?:(?:your|the|system|all|previous)\s+)*(instructions?|prompts?|rules?|safety|guidelines?|directives?|filters?)", re.I),
             "instruction_override", 0.9),
    _Pattern(re.compile(r"disregard\s+(?:(?:your|the|previous|all)\s+)*(instructions?|guidelines?|rules?|safety|safeguards?|filters?|protections?)", re.I),
             "instruction_override", 0.8),

    # ── prompt_extraction ─────────────────────────────────────────────────
    _Pattern(re.compile(r"(tell|show|reveal|print|display)\s+(?:(?:me|us)\s+)?(?:your|the|its)\s+(?:(?:system|original|base|internal)\s+)+(prompts?|instructions?|rules?|directives?)", re.I),
             "prompt_extraction", 0.9),
    _Pattern(re.compile(r"what\s+(is|are)\s+your\s+(system|base)\s+(prompt|instructions?)", re.I),
             "prompt_extraction", 0.8),
    _Pattern(re.compile(r"(begin|start|initial)\s+(system\s+)?(prompt|instruction)", re.I),
             "prompt_extraction", 0.8),

    # ── token_injection ───────────────────────────────────────────────────
    _Pattern(re.compile(r"<\|im_start\|>|<\|im_end\|>|</?\|[^|]+\|>", re.I),
             "token_injection", 1.0),

    # ── jailbreak ─────────────────────────────────────────────────────────
    _Pattern(re.compile(r"\bDAN\b|do\s*anything\s*now", re.I),
             "jailbreak", 1.0),
    _Pattern(re.compile(r"jail\s*break|jailbreak", re.I),
             "jailbreak", 0.9),
    _Pattern(re.compile(r"bypass\s+(?:(?:your|the)\s+)*(restrictions?|safeguards?|filters?|protections?|safety)", re.I),
             "jailbreak", 0.9),
    _Pattern(re.compile(r"\bpretend\b\s+(you\s+are|to\s+be|that\s+you\s+are|as\s+if|like)", re.I),
             "jailbreak", 0.7),
    _Pattern(re.compile(r"(ignore|forget|override|bypass|disregard|remove)\s+(?:(?:your|the|all|previous|its)\s+)*(filters?|safeguards?|protections?|restrictions?|rules?|guidelines?|security|safety)", re.I),
             "jailbreak", 0.9),

    # ── role_play ─────────────────────────────────────────────────────────
    _Pattern(re.compile(r"(pretend|act|role\s*play)\s+.*?(hacker|criminal|evil|malicious|unethical)", re.I),
             "role_play", 0.8),
    _Pattern(re.compile(r"you\s+are\s+(now\s+)?(a|an)\s+(hacker|criminal|evil|unethical)", re.I),
             "role_play", 0.7),
    _Pattern(re.compile(r"(act|role\s*play|impersonate)\s+as\b", re.I),
             "role_play", 0.6),
    _Pattern(re.compile(r"(override|overwrite|replace)\s+(your|the)\s+(system\s+)?(instructions?|prompts?|rules?|behaviou?r)", re.I),
             "instruction_override", 0.8),

    # ── format_manipulation ───────────────────────────────────────────────
    _Pattern(re.compile(r"(output|respond|reply)\s+(only|just)\s+(in|as|using)\s+(JSON|XML|markdown|code)", re.I),
             "format_manipulation", 0.5),
]

# Human-readable names for each category (used in block reason).
_CATEGORY_NAMES: dict[str, str] = {
    "instruction_override": "instruction override",
    "prompt_extraction": "prompt extraction",
    "token_injection": "token injection",
    "jailbreak": "jailbreak",
    "role_play": "role redefinition",
    "format_manipulation": "output format manipulation",
}


INJECTION_BLOCK_MESSAGE = (
    "Your request was blocked by the SafeNest injection filter. "
    "Please rephrase your rental query without attempting to override "
    "system instructions or extract internal prompts."
)


def check_injection(text: str) -> tuple[bool, str | None]:
    """Scan *text* against 17 known prompt-injection patterns.

    Returns
    -------
    (is_blocked, reason)
        is_blocked : `True` when any matched pattern weight >= 0.7.
        reason     : human-readable category of the highest-weight match,
                     or ``None`` when the text is clean.
    """
    if not text or not text.strip():
        return (False, None)

    best_weight = 0.0
    best_category: str | None = None

    for entry in _PATTERNS:
        if entry.pattern.search(text):
            if entry.weight > best_weight:
                best_weight = entry.weight
                best_category = entry.category

    if best_weight >= _BLOCK_THRESHOLD and best_category is not None:
        return (True, _CATEGORY_NAMES.get(best_category, best_category))

    return (False, None)


__all__ = ["check_injection", "INJECTION_BLOCK_MESSAGE"]
