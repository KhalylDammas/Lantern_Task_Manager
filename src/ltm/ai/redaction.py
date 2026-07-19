"""Redact outbound text destined for LLM / logs (C10)."""

from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{13,16}\b"), "[REDACTED_PAYMENT_IDENTIFIER]"),
    (re.compile(r"\b(IBAN)\s?[A-Z0-9]{10,}\b", re.I), "[REDACTED_IBAN]"),
]


def redact(text: str) -> str:
    out = text
    for rx, token in _PATTERNS:
        out = rx.sub(token, out)
    return out
