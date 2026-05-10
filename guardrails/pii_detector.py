"""PII detection / redaction via Microsoft Presidio — detects and anonymises
personally identifiable information in user input.

When Presidio is not installed, the module gracefully degrades and returns
empty results or the original text unchanged.
"""

from __future__ import annotations

from typing import Any

# ── lazy imports for graceful degradation ─────────────────────────────────
_PRESIDIO_AVAILABLE = False
_AnalyzerEngine: Any = None
_AnonymizerEngine: Any = None
_RecognizerRegistry: Any = None
_PatternRecognizer: Any = None

try:
    from presidio_analyzer import AnalyzerEngine as _AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine as _AnonymizerEngine
    from presidio_analyzer import PatternRecognizer as _PatternRecognizer
    from presidio_analyzer import RecognizerRegistry as _RecognizerRegistry

    _PRESIDIO_AVAILABLE = True
except ImportError:
    pass

# ── NRIC custom recognizer (Singapore National Registration Identity Card) ─
_NRIC_PATTERN = r"[STFGstfg]\d{7}[A-Za-z]"
_NRIC_REGEX_NAME = "NRIC"
_NRIC_CONTEXT = ["nric", "ic number", "identity card", "registration", "fin"]

# ── Entity types we care about ───────────────────────────────────────────
_TARGET_ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", _NRIC_REGEX_NAME]

# ── Operator tokens used by Presidio's default anonymizer ─────────────────
_ANONYMIZER_OPERATORS: dict[str, str] = {
    "PERSON": "<PERSON>",
    "PHONE_NUMBER": "<PHONE>",
    "EMAIL_ADDRESS": "<EMAIL>",
    _NRIC_REGEX_NAME: "<NRIC>",
}


_analyzer: Any = None
_anonymizer: Any = None


def _get_engine():
    """Return (analyzer, anonymizer) — lazily built on first successful call."""
    global _analyzer, _anonymizer
    if _analyzer is not None:
        return _analyzer, _anonymizer
    if not _PRESIDIO_AVAILABLE:
        return None, None
    try:
        _analyzer = _AnalyzerEngine()
        _anonymizer = _AnonymizerEngine()
        nric_recognizer = _PatternRecognizer(
            supported_entity=_NRIC_REGEX_NAME,
            patterns=[{
                "name": "NRIC (Singapore)",
                "regex": _NRIC_PATTERN,
                "score": 0.85,
            }],
            context=_NRIC_CONTEXT,
        )
        _analyzer.registry.add_recognizer(nric_recognizer)
        return _analyzer, _anonymizer
    except Exception:
        return None, None


def detect_pii(text: str) -> list[dict[str, Any]]:
    """Scan *text* for PII entities and return a list of findings.

    Each finding is a dict with keys:
        entity_type  — e.g. "PERSON", "PHONE_NUMBER", "NRIC"
        start        — character offset where the entity begins
        end          — character offset where the entity ends (exclusive)
        score        — confidence 0-1

    Returns an empty list when Presidio is unavailable or nothing is found.
    """
    if not text or not text.strip():
        return []
    if not _PRESIDIO_AVAILABLE:
        return []

    analyzer, _anonymizer_engine = _get_engine()
    if analyzer is None:
        return []

    results: list[dict[str, Any]] = []
    try:
        analyzer_results = analyzer.analyze(
            text=text,
            entities=_TARGET_ENTITIES,
            language="en",
        )
        for res in analyzer_results:
            results.append({
                "entity_type": res.entity_type,
                "start": res.start,
                "end": res.end,
                "score": round(res.score, 3) if res.score is not None else 0.0,
            })
    except Exception:
        pass  # gracefully fall through to regex fallback

    # ── regex fallback when Presidio NLP returns nothing ──────────────
    # (e.g. spaCy model not loaded for PERSON/PHONE/EMAIL)
    if not results:
        import re as _re
        # NRIC / FIN
        for m in _re.finditer(_NRIC_PATTERN, text):
            results.append({
                "entity_type": _NRIC_REGEX_NAME,
                "start": m.start(),
                "end": m.end(),
                "score": 0.85,
            })
        # Phone (Singapore: 8 digits, starting with 6/8/9, optionally +65)
        for m in _re.finditer(r"(?<!\d)(?:\+65[\s-]?)?[689]\d{3}[\s-]?\d{4}(?!\d)", text):
            results.append({
                "entity_type": "PHONE_NUMBER",
                "start": m.start(),
                "end": m.end(),
                "score": 0.85,
            })
        # Email
        for m in _re.finditer(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
            results.append({
                "entity_type": "EMAIL_ADDRESS",
                "start": m.start(),
                "end": m.end(),
                "score": 0.9,
            })
        # PERSON (simple heuristic: "My name is X" or "name: X")
        for m in _re.finditer(r"(?:My\s+name\s+is|I\s+am|name\s*[:=])\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})", text):
            # Use the captured group's span, not the full match span
            name_match = m.group(1)
            start_offset = m.start(1)
            results.append({
                "entity_type": "PERSON",
                "start": start_offset,
                "end": start_offset + len(name_match),
                "score": 0.7,
            })

    return results


def anonymize_pii(text: str) -> str:
    """Replace detected PII spans in *text* with placeholders like ``<PERSON>``.

    Returns the original text unchanged when Presidio is unavailable or
    no entities are found.
    """
    if not text or not text.strip():
        return text
    if not _PRESIDIO_AVAILABLE:
        return text

    analyzer, anonymizer = _get_engine()
    if analyzer is None or anonymizer is None:
        return text

    try:
        analyzer_results = analyzer.analyze(
            text=text,
            entities=_TARGET_ENTITIES,
            language="en",
        )
        if not analyzer_results:
            return text

        anonymized = _anonymizer.anonymize(
            text=text,
            analyzer_results=analyzer_results,
            operators={
                entity: {"type": "replace", "new_value": token}
                for entity, token in _ANONYMIZER_OPERATORS.items()
            },
        )
        return anonymized.text if hasattr(anonymized, "text") else text
    except Exception:
        return text


__all__ = ["detect_pii", "anonymize_pii"]
