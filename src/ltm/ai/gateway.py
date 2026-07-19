"""Resilient Groq LLM gateway with fallback, retries, and governance (C09)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from microsoft_teams.ai import AIModel, Function, Memory, Message, ModelMessage, SystemMessage
from openai import APIConnectionError, APITimeoutError
from pydantic import BaseModel
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from ltm.ai.circuit_breaker import CircuitBreaker, LLMCircuitOpenError
from ltm.ai.governor import LLMDailyCapExceededError, LLMGovernor, LLMRateLimitError
from ltm.ai.groq_completions_model import GroqOpenAICompletionsAIModel
from ltm.ai.groq_metrics import clear_call_metrics, get_call_metrics
from ltm.config.settings import Settings
from ltm.ai.groq_rate_limit import parse_groq_retry_seconds
from ltm.storage.llm_usage import LLMUsageRepository, UsageOutcome

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
LLMCallOutcome = Literal[
    "success", "retry", "fallback", "circuit_open", "daily_cap", "rate_limit", "error"
]

_governor_singleton: LLMGovernor | None = None
_breaker_singleton: CircuitBreaker | None = None


def get_llm_governor(settings: Settings) -> LLMGovernor:
    global _governor_singleton
    if _governor_singleton is None:
        _governor_singleton = LLMGovernor(settings=settings)
    return _governor_singleton


def get_llm_circuit_breaker(settings: Settings) -> CircuitBreaker:
    global _breaker_singleton
    if _breaker_singleton is None:
        _breaker_singleton = CircuitBreaker(
            failure_threshold=settings.llm_circuit_failure_threshold,
            open_seconds=settings.llm_circuit_open_seconds,
        )
    return _breaker_singleton


def reset_llm_runtime_state() -> None:
    """Clear singleton governor/breaker (tests)."""
    global _governor_singleton, _breaker_singleton
    _governor_singleton = None
    _breaker_singleton = None


def _groq_error_text(exc: BaseException) -> str:
    return str(exc).lower()


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, (APITimeoutError, APIConnectionError, asyncio.TimeoutError)):
        return True
    retryable_status = {413, 429, 502, 503, 504}
    status = getattr(exc, "status_code", None)
    if status in retryable_status:
        return True
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) in retryable_status:
        return True
    text = _groq_error_text(exc)
    if any(
        marker in text
        for marker in (
            "rate_limit_exceeded",
            "rate limit",
            "request too large",
            "tokens per minute",
            "tpm",
        )
    ):
        return True
    return False


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _build_groq_model(settings: Settings, model_id: str, api_key: str) -> GroqOpenAICompletionsAIModel:
    return GroqOpenAICompletionsAIModel(
        model=model_id,
        key=api_key,
        base_url=GROQ_BASE_URL,
    )


def build_resilient_groq_model(settings: Settings) -> ResilientGroqModel:
    api_key = settings.effective_groq_api_key()
    if not api_key:
        raise ValueError("GROQ_API_KEY is required when LLM_PRIMARY=groq")
    primary = _build_groq_model(settings, settings.groq_model, api_key)
    fallback = _build_groq_model(settings, settings.groq_fallback_model, api_key)
    return ResilientGroqModel(
        settings=settings,
        primary=primary,
        fallback=fallback,
        governor=get_llm_governor(settings),
        breaker=get_llm_circuit_breaker(settings),
    )


def llm_health_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    from ltm.config.settings import get_settings

    settings = settings or get_settings()
    breaker = get_llm_circuit_breaker(settings)
    totals = DailyUsageTotalsSafe.get()
    return {
        "ok": breaker.state.value != "open",
        "primary": settings.groq_model,
        "fallback": settings.groq_fallback_model,
        "circuit_state": breaker.state.value,
        "tool_profile": settings.llm_tool_profile,
        "daily_requests": totals.request_count,
        "daily_tokens": totals.prompt_tokens + totals.completion_tokens,
    }


class DailyUsageTotalsSafe:
    """Best-effort daily totals for /health without failing the route."""

    @staticmethod
    def get():
        from ltm.storage.llm_usage import DailyUsageTotals, LLMUsageRepository

        try:
            return LLMUsageRepository().get_daily_totals()
        except Exception:  # noqa: BLE001
            return DailyUsageTotals()


@dataclass
class ResilientGroqModel(AIModel):
    settings: Settings
    primary: GroqOpenAICompletionsAIModel
    fallback: GroqOpenAICompletionsAIModel
    governor: LLMGovernor
    breaker: CircuitBreaker
    _usage_repo: LLMUsageRepository = field(default_factory=LLMUsageRepository)

    @property
    def primary_model_id(self) -> str:
        return self.settings.groq_model

    @property
    def fallback_model_id(self) -> str:
        return self.settings.groq_fallback_model

    async def generate_text(
        self,
        input: Message,
        *,
        system: SystemMessage | None = None,
        memory: Memory | None = None,
        functions: dict[str, Function[BaseModel]] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ModelMessage:
        try:
            self.breaker.ensure_closed_or_half_open()
        except LLMCircuitOpenError:
            self._log_call(outcome="circuit_open", model=self.primary_model_id)
            raise

        try:
            await self.governor.acquire()
        except LLMDailyCapExceededError as exc:
            self._log_call(outcome="daily_cap", model=self.primary_model_id, error=str(exc))
            raise
        except LLMRateLimitError as exc:
            self._log_call(outcome="rate_limit", model=self.primary_model_id, error=str(exc))
            raise

        try:
            result, used_fallback = await self._call_with_retries_and_fallback(
                input,
                system=system,
                memory=memory,
                functions=functions,
                on_chunk=on_chunk,
            )
            self.breaker.record_success()
            metrics = get_call_metrics()
            prompt_tokens = metrics.prompt_tokens if metrics else 0
            completion_tokens = metrics.completion_tokens if metrics else 0
            latency_ms = metrics.latency_ms if metrics else 0.0
            model_id = self.fallback_model_id if used_fallback else self.primary_model_id
            outcome: LLMCallOutcome = "fallback" if used_fallback else "success"
            self.governor.record_token_usage(prompt_tokens, completion_tokens)
            self._log_call(
                outcome=outcome,
                model=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )
            self._schedule_usage_record(
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                outcome="fallback" if used_fallback else "success",
            )
            clear_call_metrics()
            return result
        except Exception as exc:
            self.breaker.record_failure()
            self._log_call(outcome="error", model=self.primary_model_id, error=str(exc))
            self._schedule_usage_record(
                model_id=self.primary_model_id,
                outcome="error",
            )
            clear_call_metrics()
            raise

    async def _call_with_retries_and_fallback(
        self,
        input: Message,
        *,
        system: SystemMessage | None,
        memory: Memory | None,
        functions: dict[str, Function[BaseModel]] | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[ModelMessage, bool]:
        last_error: Exception | None = None
        try:
            result = await self._call_with_retries(
                self.primary,
                input,
                system=system,
                memory=memory,
                functions=functions,
                on_chunk=on_chunk,
            )
            return result, False
        except Exception as exc:
            last_error = exc
            if not self.settings.llm_fallback_enabled or not _is_retryable_error(exc):
                raise

        logger.warning(
            "Primary Groq model failed (%s); attempting fallback model=%s",
            last_error,
            self.fallback_model_id,
        )
        try:
            await self.governor.acquire()
        except (LLMDailyCapExceededError, LLMRateLimitError):
            raise
        result = await self._call_once(
            self.fallback,
            input,
            system=system,
            memory=memory,
            functions=functions,
            on_chunk=on_chunk,
        )
        return result, True

    async def _call_with_retries(
        self,
        model: GroqOpenAICompletionsAIModel,
        input: Message,
        *,
        system: SystemMessage | None,
        memory: Memory | None,
        functions: dict[str, Function[BaseModel]] | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> ModelMessage:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max(1, self.settings.llm_retry_max_attempts)),
            wait=wait_exponential_jitter(initial=1, max=30),
            retry=retry_if_exception(_is_retryable_error),
            reraise=True,
        ):
            with attempt:
                try:
                    return await asyncio.wait_for(
                        self._call_once(
                            model,
                            input,
                            system=system,
                            memory=memory,
                            functions=functions,
                            on_chunk=on_chunk,
                        ),
                        timeout=self.settings.llm_request_timeout_seconds,
                    )
                except Exception as exc:
                    delay = _retry_after_seconds(exc)
                    if delay is None and _is_retryable_error(exc):
                        delay = parse_groq_retry_seconds(exc, default=0.0)
                    if delay is not None and delay > 0 and _is_retryable_error(exc):
                        await asyncio.sleep(min(delay, 60.0))
                    raise
        raise RuntimeError("unreachable")

    async def _call_once(
        self,
        model: GroqOpenAICompletionsAIModel,
        input: Message,
        *,
        system: SystemMessage | None,
        memory: Memory | None,
        functions: dict[str, Function[BaseModel]] | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> ModelMessage:
        return await model.generate_text(
            input,
            system=system,
            memory=memory,
            functions=functions,
            on_chunk=on_chunk,
        )

    def _log_call(
        self,
        *,
        outcome: LLMCallOutcome,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        error: str = "",
    ) -> None:
        logger.info(
            "llm_call provider=groq model=%s outcome=%s latency_ms=%.1f "
            "prompt_tokens=%s completion_tokens=%s error=%s",
            model,
            outcome,
            latency_ms,
            prompt_tokens,
            completion_tokens,
            error[:200] if error else "",
        )

    def _schedule_usage_record(
        self,
        *,
        model_id: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        outcome: UsageOutcome = "success",
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _record() -> None:
            try:
                await asyncio.to_thread(
                    self._usage_repo.record_usage,
                    provider="groq",
                    model_id=model_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    outcome=outcome,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to record LLM usage: %s", exc)

        loop.create_task(_record())
