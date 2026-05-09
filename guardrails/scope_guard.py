"""Out-of-scope refusal (legal advice etc.) — B.

Ensures the SafeNest assistant stays within its defined scope — a rental
assessment tool — and refuses to give legal, immigration, or other
professional advice that requires a qualified human practitioner.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Out-of-scope patterns (regex, case-insensitive)
# ---------------------------------------------------------------------------
OUT_OF_SCOPE_PATTERNS: list[tuple[str, str]] = [
    # --- Legal advice ---
    (r"(draft|write|prepare)\s+(my\s+|a\s+)?(legal\s+|law\s+)?(document|contract|letter|notice|will)",
     "legal_document_drafting"),
    (r"(sue|lawsuit|litigation|suing)\b",
     "legal_action"),
    (r"\blegal\s+(advice|opinion|representation|action)\b",
     "legal_advice"),
    (r"\bsmall\s+claims\s+(tribunal|court)\b",
     "legal_advice"),
    (r"\btenant\s+(rights|law|act|dispute)\b",
     "legal_advice"),

    # --- Immigration / visa ---
    (r"(immigration|visa|work\s+pass|employment\s+pass|PR\s+application|permanent\s+residen)",
     "immigration_advice"),
    (r"\bICA\b.*\b(apply|approve|reject)\b",
     "immigration_advice"),
    (r"\bMOM\b.*\b(pass|approval|quota)\b",
     "immigration_advice"),

    # --- Financial / investment ---
    (r"(guarantee\s+(approval|success|pass|return|profit)|100%\s+(approved|guaranteed))",
     "financial_guarantee"),
    (r"\binvest\b.*\b(property|real\s+estate)\b.*\badvice\b",
     "financial_advice"),
    (r"\b(can't\s+lose|risk[\s-]free|guaranteed\s+return)\b",
     "financial_guarantee"),

    # --- Medical / safety ---
    (r"\b(medical|health)\s+(advice|condition|diagnosis)\b",
     "medical_advice"),

    # --- Discrimination / harassment ---
    (r"\b(discriminat|harass|racial\s+quota|CMI\b)",
     "discrimination"),

    # --- Explicit / NSFW ---
    (r"\b(porn|escort|massage\s+parlour|vice)\b",
     "nsfw"),
]

# ---------------------------------------------------------------------------
# Refusal template
# ---------------------------------------------------------------------------
SCOPE_REFUSAL_TEMPLATE = (
    "I'm a rental assessment assistant focused on helping tenants evaluate "
    "Singapore rental properties.  I cannot provide legal advice, immigration "
    "counsel, financial guarantees, or medical opinions.\n\n"
    "For this question, please consult a qualified professional:\n"
    "- Legal matters: visit [cea.gov.sg](https://www.cea.gov.sg) or consult a lawyer\n"
    "- Immigration / visa: visit [ica.gov.sg](https://www.ica.gov.sg)\n"
    "- Tenancy disputes: contact the Community Justice Centre or Small Claims Tribunal\n\n"
    "If you have a rental-related question (location, pricing, contract review, "
    "agent verification), I'm happy to help!"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_scope(text: str | None) -> dict[str, Any]:
    """Check whether *text* falls within SafeNest's defined scope.

    Args:
        text: The user query or assistant response to check.

    Returns:
        ``{"in_scope": bool, "reason": str | None, "matched_category": str | None}``
    """
    if not text:
        return {"in_scope": True, "reason": None, "matched_category": None}

    for pattern, category in OUT_OF_SCOPE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return {
                "in_scope": False,
                "reason": (
                    f"Query matches out-of-scope category '{category}'. "
                    "SafeNest only handles rental assessment."
                ),
                "matched_category": category,
                "matched_text": match.group(0),
            }

    return {"in_scope": True, "reason": None, "matched_category": None}


def apply_scope_guard(text: str | None) -> str:
    """If *text* is out of scope, return the refusal template.
    Otherwise return the original text unchanged.
    """
    scope_result = check_scope(text)
    if not scope_result["in_scope"]:
        return SCOPE_REFUSAL_TEMPLATE
    return text or ""


__all__ = [
    "OUT_OF_SCOPE_PATTERNS",
    "SCOPE_REFUSAL_TEMPLATE",
    "apply_scope_guard",
    "check_scope",
]

