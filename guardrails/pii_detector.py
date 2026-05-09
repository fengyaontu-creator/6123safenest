"""PII detection / redaction (Presidio) — B.

Wraps Microsoft Presidio for detecting and redacting personally identifiable
information before it reaches downstream LLM agents.

Fallback: if Presidio is not installed or its model download fails, the
module degrades gracefully — ``detect_pii`` returns an empty list and
``redact_pii`` returns the original text unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy initialisation (Presidio models are ~50‑100 MB, downloaded on first use)
# ---------------------------------------------------------------------------

_analyzer: Any = None
_anonymizer: Any = None
_presidio_available: bool | None = None  # tri-state: None = not tried yet


def _init_presidio() -> bool:
    """Try to import + warm Presidio.  Returns True on success."""
    global _analyzer, _anonymizer, _presidio_available

    if _presidio_available is not None:
        return _presidio_available

    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]
        from presidio_anonymizer import AnonymizerEngine  # type: ignore[import-untyped]

        _analyzer = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()
        _presidio_available = True
        logger.info("Presidio initialised successfully")
    except Exception as exc:
        _presidio_available = False
        logger.warning("Presidio unavailable — PII detection disabled: %s", exc)

    return _presidio_available


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_pii(text: str | None) -> list[dict[str, Any]]:
    """Detect PII entities in *text*.

    Returns:
        A list of dicts, each with keys ``type`` (e.g. PERSON, PHONE_NUMBER),
        ``start``, ``end``, and ``score`` (0‑1 confidence).
        Returns an empty list when Presidio is unavailable or *text* is empty.
    """
    if not text or not _init_presidio():
        return []

    try:
        results = _analyzer.analyze(text=text, language="en")  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("Presidio analysis failed: %s", exc)
        return []

    return [
        {
            "type": result.entity_type,
            "start": result.start,
            "end": result.end,
            "score": round(result.score, 3),
        }
        for result in results
    ]


def redact_pii(text: str | None) -> str:
    """Replace detected PII entities with type‑based placeholders.

    Returns the redacted string, or the original text if Presidio is
    unavailable or *text* is empty / contains no PII.
    """
    if not text or not _init_presidio():
        return text or ""

    entities = detect_pii(text)
    if not entities:
        return text

    try:
        # Presidio anonymizer expects a specific format
        presidio_results = [
            {
                "start": e["start"],
                "end": e["end"],
                "entity_type": e["type"],
            }
            for e in entities
        ]
        result = _anonymizer.anonymize(  # type: ignore[union-attr]
            text=text, analyzer_results=presidio_results
        )
        return result.text if hasattr(result, "text") else str(result)
    except Exception as exc:
        logger.warning("Presidio anonymization failed: %s", exc)
        return text


def has_pii(text: str | None) -> bool:
    """Quick check: does *text* contain any detectable PII?"""
    return len(detect_pii(text)) > 0


__all__ = ["detect_pii", "has_pii", "redact_pii"]

