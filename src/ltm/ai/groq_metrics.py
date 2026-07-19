"""Per-request Groq API call metrics via contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class GroqCallMetrics:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    ttft_ms: float | None = None


_current_metrics: ContextVar[GroqCallMetrics | None] = ContextVar("groq_call_metrics", default=None)


def begin_call() -> None:
    _current_metrics.set(GroqCallMetrics())


def get_call_metrics() -> GroqCallMetrics | None:
    return _current_metrics.get()


def clear_call_metrics() -> None:
    _current_metrics.set(None)
