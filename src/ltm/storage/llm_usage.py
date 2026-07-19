"""Daily LLM usage persistence for governance caps and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import select

from ltm.storage.db import session_scope
from ltm.storage.orm import LlmUsageDaily

UsageOutcome = Literal["success", "fallback", "error"]


@dataclass(frozen=True)
class DailyUsageTotals:
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fallback_count: int = 0
    error_count: int = 0


class LLMUsageRepository:
    def _today(self) -> date:
        return datetime.now(UTC).date()

    def get_daily_totals(self, usage_date: date | None = None) -> DailyUsageTotals:
        target = usage_date or self._today()
        with session_scope() as session:
            rows = session.scalars(
                select(LlmUsageDaily).where(LlmUsageDaily.usage_date == target)
            ).all()
            snapshots = [
                DailyUsageTotals(
                    request_count=row.request_count,
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    fallback_count=row.fallback_count,
                    error_count=row.error_count,
                )
                for row in rows
            ]
        totals = DailyUsageTotals()
        for snap in snapshots:
            totals = DailyUsageTotals(
                request_count=totals.request_count + snap.request_count,
                prompt_tokens=totals.prompt_tokens + snap.prompt_tokens,
                completion_tokens=totals.completion_tokens + snap.completion_tokens,
                fallback_count=totals.fallback_count + snap.fallback_count,
                error_count=totals.error_count + snap.error_count,
            )
        return totals

    def record_usage(
        self,
        *,
        provider: str,
        model_id: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        outcome: UsageOutcome = "success",
        usage_date: date | None = None,
    ) -> None:
        target = usage_date or self._today()
        fallback_inc = 1 if outcome == "fallback" else 0
        error_inc = 1 if outcome == "error" else 0
        with session_scope() as session:
            row = session.scalar(
                select(LlmUsageDaily).where(
                    LlmUsageDaily.usage_date == target,
                    LlmUsageDaily.provider == provider,
                    LlmUsageDaily.model_id == model_id,
                )
            )
            if row is None:
                session.add(
                    LlmUsageDaily(
                        usage_date=target,
                        provider=provider,
                        model_id=model_id,
                        request_count=1,
                        prompt_tokens=max(0, prompt_tokens),
                        completion_tokens=max(0, completion_tokens),
                        fallback_count=fallback_inc,
                        error_count=error_inc,
                    )
                )
                return
            row.request_count += 1
            row.prompt_tokens += max(0, prompt_tokens)
            row.completion_tokens += max(0, completion_tokens)
            row.fallback_count += fallback_inc
            row.error_count += error_inc
