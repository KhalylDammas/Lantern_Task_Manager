from __future__ import annotations

from ltm.ai.circuit_breaker import CircuitBreaker, CircuitState, LLMCircuitOpenError
from ltm.ai.groq_rate_limit import is_groq_rate_limit_error, parse_groq_retry_seconds
from ltm.config.settings import Settings
from ltm.domain.business_time import RIYADH, business_now, business_today


def test_business_clock_uses_riyadh_timezone():
    now = business_now()
    assert now.tzinfo == RIYADH
    assert business_today() == now.date()


def test_circuit_breaker_opens_then_recovers(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("ltm.ai.circuit_breaker.time.monotonic", lambda: clock[0])
    breaker = CircuitBreaker(failure_threshold=2, open_seconds=5.0)

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    try:
        breaker.ensure_closed_or_half_open()
    except LLMCircuitOpenError:
        pass
    else:
        raise AssertionError("open circuit accepted a request")

    clock[0] = 16.0
    assert breaker.state == CircuitState.HALF_OPEN
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_groq_retry_parser_and_detection():
    exc = RuntimeError("rate_limit_exceeded: Please try again in 7.25s")
    assert is_groq_rate_limit_error(exc)
    assert parse_groq_retry_seconds(exc) == 7.75


def test_explicit_groq_key_wins_over_legacy_openai_key():
    settings = Settings(GROQ_API_KEY="groq-key", OPENAI_API_KEY="legacy-key")
    assert settings.effective_groq_api_key() == "groq-key"
