"""Business timezone helpers (Asia/Riyadh, UTC+3).

Persisted timestamps and calendar-day boundaries use Saudi time so audit
trails, idempotency day keys, and overdue checks align with business hours.
Riyadh has no daylight saving, so the offset is a stable +03:00.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

RIYADH = ZoneInfo("Asia/Riyadh")


def business_now() -> datetime:
    """Timezone-aware current time in Riyadh (+03:00)."""
    return datetime.now(RIYADH)


def business_today() -> date:
    """Current calendar date in Riyadh."""
    return business_now().date()
