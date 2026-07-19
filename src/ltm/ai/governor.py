"""LLM rate limiting and daily cap checks (C09)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ltm.config.settings import Settings
from ltm.storage.llm_usage import LLMUsageRepository

logger = logging.getLogger(__name__)


class LLMRateLimitError(RuntimeError):
    """Raised when in-process rate limits or daily caps block an LLM request."""


class LLMDailyCapExceededError(LLMRateLimitError):
    """Raised when configured daily request/token limits are exceeded."""


@dataclass
class _TokenBucket:
    capacity: float
    refill_per_second: float
    tokens: float = field(init=False)
    last_refill: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.last_refill = now

    async def acquire(self, amount: float = 1.0, *, max_wait: float) -> None:
        deadline = time.monotonic() + max_wait
        while True:
            self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                return
            if time.monotonic() >= deadline:
                raise LLMRateLimitError(
                    f"Rate limit bucket exhausted (need {amount}, have {self.tokens:.2f})"
                )
            await asyncio.sleep(min(0.05, deadline - time.monotonic()))


@dataclass
class LLMGovernor:
    settings: Settings
    _rpm_bucket: _TokenBucket = field(init=False)
    _tpm_bucket: _TokenBucket = field(init=False)
    _last_request_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        rpm = max(1, self.settings.llm_rate_limit_rpm)
        tpm = max(1, self.settings.llm_rate_limit_tpm)
        self._rpm_bucket = _TokenBucket(capacity=float(rpm), refill_per_second=rpm / 60.0)
        self._tpm_bucket = _TokenBucket(capacity=float(tpm), refill_per_second=tpm / 60.0)

    def _check_daily_caps(self) -> None:
        daily_req_limit = self.settings.llm_daily_request_limit
        daily_token_limit = self.settings.llm_daily_token_limit
        if daily_req_limit <= 0 and daily_token_limit <= 0:
            return
        try:
            totals = LLMUsageRepository().get_daily_totals()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Daily LLM cap check skipped (usage store unavailable): %s", exc)
            return
        if daily_req_limit > 0 and totals.request_count >= daily_req_limit:
            raise LLMDailyCapExceededError(
                f"Daily request limit exceeded ({totals.request_count}/{daily_req_limit})"
            )
        total_tokens = totals.prompt_tokens + totals.completion_tokens
        if daily_token_limit > 0 and total_tokens >= daily_token_limit:
            raise LLMDailyCapExceededError(
                f"Daily token limit exceeded ({total_tokens}/{daily_token_limit})"
            )

    async def acquire(self, *, estimated_tokens: int = 0) -> None:
        self._check_daily_caps()
        max_wait = self.settings.llm_governor_max_wait_seconds
        await self._rpm_bucket.acquire(1.0, max_wait=max_wait)
        token_cost = max(1.0, float(estimated_tokens)) if estimated_tokens > 0 else 1.0
        await self._tpm_bucket.acquire(token_cost, max_wait=max_wait)
        min_interval_ms = self.settings.llm_request_min_interval_ms
        if min_interval_ms > 0 and self._last_request_at is not None:
            elapsed_ms = (time.monotonic() - self._last_request_at) * 1000.0
            remaining_ms = min_interval_ms - elapsed_ms
            if remaining_ms > 0:
                if remaining_ms / 1000.0 > max_wait:
                    raise LLMRateLimitError("Minimum request interval not elapsed")
                await asyncio.sleep(remaining_ms / 1000.0)
        self._last_request_at = time.monotonic()

    def record_token_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Debit actual token usage against the TPM bucket after a call completes."""
        actual = max(0, prompt_tokens) + max(0, completion_tokens)
        if actual <= 1:
            return
        extra = float(actual - 1)
        self._tpm_bucket.tokens = max(0.0, self._tpm_bucket.tokens - extra)
