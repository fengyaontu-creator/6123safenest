"""Guardrails — B.

Three-layer protection:
  1. Injection Filter (Guardrail-In)  — block prompt-injection attempts
  2. PII Detector     (Guardrail-In)  — detect/redact PII before logging
  3. Scope Guard      (Guardrail-Out) — refuse out-of-scope queries
"""

from guardrails.injection_filter import (
    INJECTION_BLOCK_MESSAGE,
    check_injection,
)
from guardrails.pii_detector import (
    detect_pii,
    redact_pii,
)
from guardrails.scope_guard import (
    SCOPE_REFUSAL_TEMPLATE,
    check_scope,
)

__all__ = [
    "INJECTION_BLOCK_MESSAGE",
    "SCOPE_REFUSAL_TEMPLATE",
    "check_injection",
    "check_scope",
    "detect_pii",
    "redact_pii",
]
