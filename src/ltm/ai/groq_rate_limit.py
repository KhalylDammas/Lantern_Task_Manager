"""Groq rate-limit helpers shared by gateway and eval harness."""

from __future__ import annotations

import re


_RETRY_IN_SECONDS = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)


def is_groq_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if any(
        marker in text
        for marker in ("429", "413", "rate_limit", "rate limit", "request too large", "tokens per minute")
    ):
        return True
    status = getattr(exc, "status_code", None)
    return status in {413, 429}


def parse_groq_retry_seconds(exc: BaseException, *, default: float = 30.0) -> float:
    """Parse Groq error message: 'Please try again in 7.612499999s'."""
    match = _RETRY_IN_SECONDS.search(str(exc))
    if not match:
        response = getattr(exc, "response", None)
        if response is not None:
            body = getattr(response, "text", None) or ""
            match = _RETRY_IN_SECONDS.search(body)
    if match:
        return float(match.group(1)) + 0.5
    return default
