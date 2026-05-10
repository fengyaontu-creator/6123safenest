"""PII detector — B + D contributions.

Detects PERSON / PHONE_NUMBER / EMAIL_ADDRESS / NRIC entities in free text.

Two-tier detection:
  1. Presidio (if installed AND its spaCy model loads) — covers PERSON via NLP
     plus our custom NRIC PatternRecognizer.
  2. Regex fallback — runs whenever Presidio is unavailable or returns nothing.
     Catches NRIC, EMAIL, SG phone (with/without +65), and contextual PERSON.

Empty input or completely missing Presidio -> empty list (graceful degradation).
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Singapore NRIC: starts with S/T/F/G, 7 digits, ends with a checksum letter.
_NRIC_PATTERN = r"\b[STFGstfg]\d{7}[A-Za-z]\b"
_NRIC_REGEX = re.compile(_NRIC_PATTERN)

# RFC-ish email — sufficient for guardrail detection (not validation).
_EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Singapore mobile/landline — 8 digits, 6/8/9 prefix, optional +65 with space/dash.
_SG_PHONE_REGEX = re.compile(r"(?<!\d)(?:\+65[\s-]?)?[689]\d{3}[\s-]?\d{4}(?!\d)")

# PERSON via context cues. Used when Presidio's NLP is unavailable.
_PERSON_REGEX = re.compile(
    r"(?:my\s+name\s+is|i\s+am|i'm|this\s+is|call\s+me)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
    re.IGNORECASE,
)

_TARGET_ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "NRIC"]
_NRIC_CONTEXT = ["nric", "ic number", "identity card", "registration", "fin"]


# ---------------------------------------------------------------------------
# Presidio engine (lazy-init; gracefully None if unavailable)
# ---------------------------------------------------------------------------

_engine_cache: tuple[Any, Any] | None = None  # (analyzer, anonymizer) or (None, None)


def _presidio_available() -> bool:
    try:
        import presidio_analyzer  # noqa: F401
    except ImportError:
        return False
    return True


def _get_engine() -> tuple[Any, Any]:
    """Return (analyzer, anonymizer); both None when Presidio cannot initialise."""
    global _engine_cache
    if _engine_cache is not None:
        return _engine_cache

    if not _presidio_available():
        _engine_cache = (None, None)
        return _engine_cache

    try:
        from presidio_analyzer import AnalyzerEngine, PatternRecognizer
        from presidio_anonymizer import AnonymizerEngine

        analyzer = AnalyzerEngine()
        nric_recognizer = PatternRecognizer(
            supported_entity="NRIC",
            patterns=[{
                "name": "NRIC (Singapore)",
                "regex": _NRIC_PATTERN,
                "score": 0.85,
            }],
            context=_NRIC_CONTEXT,
        )
        analyzer.registry.add_recognizer(nric_recognizer)
        anonymizer = AnonymizerEngine()
        _engine_cache = (analyzer, anonymizer)
    except Exception:
        # Presidio installed but spaCy model missing or recognizer build failed.
        _engine_cache = (None, None)

    return _engine_cache


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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

    # Tier 1 — Presidio NLP (PERSON, etc.) when engine builds successfully
    analyzer, _ = _get_engine()
    if analyzer is not None:
        try:
            for res in analyzer.analyze(
                text=text,
                entities=_TARGET_ENTITIES,
                language="en",
            ):
                entities.append({
                    "entity_type": res.entity_type,
                    "start": res.start,
                    "end": res.end,
                    "score": round(res.score, 3) if res.score is not None else 0.0,
                    "text": text[res.start:res.end],
                })
        except Exception:
            pass  # fall through to regex

    if entities:
        return entities

    # Tier 2 — pure regex fallback
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
