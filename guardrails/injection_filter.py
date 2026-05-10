"""Prompt-injection filter — B.

Regex-based detector for prompt injection attempts. Returns block info on hit
or None on pass. Used at orchestrator entry to reject malicious user input
before it reaches the LLM.
"""

from __future__ import annotations

import re
from typing import Optional

INJECTION_BLOCK_MESSAGE = (
    "Your input was blocked by SafeNest's injection filter. "
    "Please rephrase your rental question without instructions to override, "
    "extract, or bypass system behavior."
)

# (regex_pattern, weight) — weight is informational, kept aligned with the
# guardrail report's per-category weight ranges.
_INSTRUCTION_OVERRIDE = [
    (r"ignore\s+(?:all\s+)?(?:previous|prior|the\s+above)\s+instructions?", 0.9),
    (r"forget\s+(?:everything|all|you\s+know|your\s+(?:training|instructions))", 0.85),
    (r"disregard\s+(?:all\s+)?(?:previous|prior|the\s+above|your)\s+\w+", 0.8),
    (r"override\s+(?:your|the)\s+(?:instructions|rules|safety|guidelines)", 0.85),
    (r"new\s+instructions?\s*[:：]", 0.7),
]

_PROMPT_EXTRACTION = [
    (r"(?:tell|show|reveal|print|repeat)\s+(?:me\s+)?your\s+(?:system\s+)?(?:prompt|instructions)", 0.9),
    (r"what\s+(?:are|were)\s+your\s+(?:original\s+)?(?:instructions|system\s+prompt)", 0.85),
    (r"(?:reveal|expose|leak)\s+your\s+(?:system|configuration|prompt)", 0.8),
]

_TOKEN_INJECTION = [
    (r"<\|im_(?:start|end|sep)\|>", 1.0),
]

_JAILBREAK = [
    (r"\bDAN\b(?:\s+(?:mode|prompt|do\s+anything))?", 1.0),
    (r"do\s+anything\s+now", 0.95),
    (r"bypass\s+(?:your|the|all)\s+(?:restrictions|rules|filters|safety)", 0.85),
    (r"\bno\s+(?:restrictions|rules|safety|filters)\b", 0.7),
]

_ROLE_PLAY = [
    (r"you\s+are\s+(?:now\s+)?(?:a|an)\s+different\s+\w+", 0.8),
    (r"pretend\s+you\s+(?:are|to\s+be)\s+\w+", 0.7),
    (r"act\s+as\s+(?:a|an|if)\s+\w+", 0.6),
]

_FORMAT_MANIPULATION = [
    (r"output\s+(?:only\s+)?(?:in|as)\s+(?:json|xml|raw|base64)", 0.5),
]

_PATTERNS_BY_CATEGORY: dict[str, list[tuple[str, float]]] = {
    "instruction_override": _INSTRUCTION_OVERRIDE,
    "prompt_extraction": _PROMPT_EXTRACTION,
    "token_injection": _TOKEN_INJECTION,
    "jailbreak": _JAILBREAK,
    "role_play": _ROLE_PLAY,
    "format_manipulation": _FORMAT_MANIPULATION,
}

_COMPILED: list[tuple[str, re.Pattern[str], float]] = [
    (category, re.compile(pattern, re.IGNORECASE), weight)
    for category, patterns in _PATTERNS_BY_CATEGORY.items()
    for pattern, weight in patterns
]


def check_injection(text: Optional[str]) -> Optional[dict]:
    """Return block info if `text` matches an injection pattern, else None.

    Empty/None input passes (treated as benign no-op).
    """

    if not text or not text.strip():
        return None

    for category, regex, weight in _COMPILED:
        match = regex.search(text)
        if match:
            return {
                "blocked": True,
                "category": category,
                "pattern": regex.pattern,
                "weight": weight,
                "match": match.group(0),
                "message": INJECTION_BLOCK_MESSAGE,
            }
    return None


__all__ = [
    "INJECTION_BLOCK_MESSAGE",
    "check_injection",
]
