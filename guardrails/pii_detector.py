"""PII detector — B.

Detects PERSON / PHONE_NUMBER / EMAIL_ADDRESS / NRIC entities in free text.
Wraps Microsoft Presidio for the import-availability check, but does the
actual matching with deterministic regex so tests do not require a spaCy
model download. Falls back to an empty list when Presidio is unavailable.
"""

from __future__ import annotations

import re
from typing import Optional

# Singapore NRIC: starts with S/T/F/G, 7 digits, ends with a checksum letter.
_NRIC_REGEX = re.compile(r"\b[STFGstfg]\d{7}[A-Za-z]\b")

# RFC-ish email — sufficient for guardrail detection (not validation).
_EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Singapore mobile/landline — 8 digits, starts with 6/8/9 (no country code).
_SG_PHONE_REGEX = re.compile(r"(?<!\d)[689]\d{7}(?!\d)")

# PERSON via context cues. Avoids needing a spaCy NER model in CI.
_PERSON_REGEX = re.compile(
    r"(?:my\s+name\s+is|i\s+am|i'm|this\s+is|call\s+me)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
    re.IGNORECASE,
)


def _presidio_available() -> bool:
    """Return True iff the presidio_analyzer module can be imported."""
    try:
        import presidio_analyzer  # noqa: F401
    except ImportError:
        return False
    return True


def detect_pii(text: Optional[str]) -> list[dict]:
    """Return a list of detected PII entities, or [] on empty input or when
    Presidio is unavailable.

    Each entity dict: {"entity_type", "start", "end", "score", "text"}.
    """

    if not text or not text.strip():
        return []

    if not _presidio_available():
        return []

    entities: list[dict] = []

    for match in _NRIC_REGEX.finditer(text):
        entities.append({
            "entity_type": "NRIC",
            "start": match.start(),
            "end": match.end(),
            "score": 0.95,
            "text": match.group(0),
        })

    for match in _EMAIL_REGEX.finditer(text):
        entities.append({
            "entity_type": "EMAIL_ADDRESS",
            "start": match.start(),
            "end": match.end(),
            "score": 0.95,
            "text": match.group(0),
        })

    for match in _SG_PHONE_REGEX.finditer(text):
        entities.append({
            "entity_type": "PHONE_NUMBER",
            "start": match.start(),
            "end": match.end(),
            "score": 0.85,
            "text": match.group(0),
        })

    for match in _PERSON_REGEX.finditer(text):
        entities.append({
            "entity_type": "PERSON",
            "start": match.start(1),
            "end": match.end(1),
            "score": 0.75,
            "text": match.group(1),
        })

    return entities


def redact_pii(text: Optional[str]) -> str:
    """Replace detected entities with `<ENTITY_TYPE>` placeholders.

    Returns the original text unchanged when nothing is detected (or input
    is empty / Presidio unavailable).
    """

    if not text:
        return text or ""

    entities = detect_pii(text)
    if not entities:
        return text

    # Replace from rightmost to leftmost so earlier offsets stay valid.
    for ent in sorted(entities, key=lambda e: e["start"], reverse=True):
        text = text[: ent["start"]] + f"<{ent['entity_type']}>" + text[ent["end"]:]
    return text


__all__ = [
    "detect_pii",
    "redact_pii",
]
