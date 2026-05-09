"""Prompt-injection filter — B.

Detects common prompt-injection / jailbreak patterns before user input
reaches any LLM agent.  Returns a structured verdict so the caller can
decide whether to block, sanitise, or flag the request.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Injection patterns (regex, case-insensitive)
# ---------------------------------------------------------------------------
# Each tuple is (pattern, category, severity_weight).
# severity_weight is 0.0‑1.0 and contributes to the overall score.
INJECTION_PATTERNS: list[tuple[str, str, float]] = [
    # --- Direct instruction override ---
    (r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|messages?)",
     "instruction_override", 0.9),
    (r"disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)",
     "instruction_override", 0.9),
    (r"forget\s+(all\s+|everything\s+)?(you\s+know|your\s+training|previous)",
     "instruction_override", 0.9),
    (r"you\s+are\s+now\s+(a\s+)?(different|new|another)",
     "role_redefinition", 0.8),
    (r"from\s+now\s+on\s+you\s+(are|will\s+be)",
     "role_redefinition", 0.7),

    # --- System prompt extraction ---
    (r"(reveal|show|print|display|tell\s+me)\s+(your\s+)?(system\s+prompt|instructions?|rules?)",
     "prompt_extraction", 0.9),
    (r"(what|tell|show)\s+(is\s+)?(your\s+)?(system\s+)?prompt",
     "prompt_extraction", 0.8),
    (r"<\|im_start\|>|<\|im_end\|>", "token_injection", 1.0),

    # --- Jailbreak / DAN patterns ---
    (r"\bDAN\b.*\b(do\s+anything\s+now|jailbreak)\b", "jailbreak", 1.0),
    (r"jailbreak", "jailbreak", 0.8),
    (r"developer\s+mode", "jailbreak", 0.7),
    (r"bypass\s+(your\s+)?(restrictions?|limitations?|rules?|filters?)",
     "jailbreak", 0.8),

    # --- Role-play / pretend ---
    (r"pretend\s+(you\s+are|to\s+be)", "role_play", 0.7),
    (r"act\s+as\s+(if\s+)?(you\s+are|a\s+different)", "role_play", 0.6),
    (r"you\s+are\s+no\s+longer\s+(a\s+)?(an?\s+)?(AI|assistant|agent|model)",
     "role_redefinition", 0.8),

    # --- Output format manipulation ---
    (r"respond\s+(only\s+)?(with|in)\s+(JSON|XML|base64|hex)",
     "format_manipulation", 0.4),
    (r"do\s+not\s+(answer|respond|reply)\s+(with|as)",
     "format_manipulation", 0.5),
]


def detect_injection(text: str | None) -> dict[str, Any]:
    """Scan *text* for prompt-injection patterns.

    Args:
        text: Raw user input string.  ``None`` is treated as safe.

    Returns:
        ``{"flagged": bool, "score": float, "matches": list[dict]}``
        where each match has keys ``pattern``, ``category``, ``weight``,
        and ``span`` (start, end).
    """
    if not text:
        return {"flagged": False, "score": 0.0, "matches": []}

    matches: list[dict[str, Any]] = []
    total_weight = 0.0

    for pattern, category, weight in INJECTION_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            matches.append({
                "pattern": pattern,
                "category": category,
                "weight": weight,
                "span": (match.start(), match.end()),
                "matched_text": match.group(0),
            })
            total_weight += weight

    # Cap score at 1.0, flag if any pattern matched
    score = min(total_weight, 1.0)
    return {
        "flagged": len(matches) > 0,
        "score": round(score, 2),
        "matches": matches,
    }


def filter_injection(text: str | None) -> str:
    """Safe wrapper: returns an empty string if injection is detected,
    otherwise returns the original text unchanged.

    The caller should check the return value — an empty string signals
    that the input should be blocked.
    """
    if detect_injection(text)["flagged"]:
        return ""
    return text or ""


INJECTION_BLOCK_MESSAGE = (
    "Your request was blocked by the SafeNest security filter because it "
    "contains patterns that may attempt to override the assistant's "
    "instructions.  If you believe this is a mistake, please rephrase your "
    "question without special commands or role-play language."
)


__all__ = [
    "INJECTION_BLOCK_MESSAGE",
    "INJECTION_PATTERNS",
    "detect_injection",
    "filter_injection",
]
