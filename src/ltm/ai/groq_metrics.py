"""Per-turn Groq API call metrics via contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

GroqCallStage = Literal["initial", "tool_result"]


@dataclass
class GroqCallMetrics:
    stage: GroqCallStage = "initial"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    ttft_ms: float | None = None


_turn_metrics: ContextVar[tuple[GroqCallMetrics, ...]] = ContextVar("groq_turn_metrics", default=())


def begin_turn() -> None:
    """Start an isolated collection for one application-level model turn."""
    _turn_metrics.set(())


def begin_call(*, stage: GroqCallStage) -> GroqCallMetrics:
    """Append one actual provider request and return its mutable metrics."""
    metrics = GroqCallMetrics(stage=stage)
    _turn_metrics.set((*_turn_metrics.get(), metrics))
    return metrics


def get_call_metrics() -> GroqCallMetrics | None:
    """Return aggregate metrics for all provider requests in the current turn."""
    calls = _turn_metrics.get()
    if not calls:
        return None
    return GroqCallMetrics(
        prompt_tokens=sum(call.prompt_tokens for call in calls),
        completion_tokens=sum(call.completion_tokens for call in calls),
        latency_ms=sum(call.latency_ms for call in calls),
    )


def get_call_records() -> tuple[GroqCallMetrics, ...]:
    return _turn_metrics.get()


def clear_call_metrics() -> None:
    _turn_metrics.set(())
