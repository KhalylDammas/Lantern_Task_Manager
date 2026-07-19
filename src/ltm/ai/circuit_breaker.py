"""In-process LLM circuit breaker (C09)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class LLMCircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is open and LLM calls are blocked."""


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    open_seconds: float = 60.0
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def state(self) -> CircuitState:
        self._maybe_transition_from_open()
        return self._state

    def _maybe_transition_from_open(self) -> None:
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return
        if time.monotonic() - self._opened_at >= self.open_seconds:
            self._state = CircuitState.HALF_OPEN

    def allow_request(self) -> bool:
        self._maybe_transition_from_open()
        return self._state != CircuitState.OPEN

    def ensure_closed_or_half_open(self) -> None:
        if not self.allow_request():
            raise LLMCircuitOpenError(
                f"LLM circuit open after {self.failure_threshold} consecutive failures"
            )

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
