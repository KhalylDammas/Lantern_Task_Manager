"""Deterministic normalization for low-friction natural-language task capture."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from dateparser import parse as parse_natural_date
from dateparser.search import search_dates

from ltm.domain.business_time import RIYADH, business_now
from ltm.domain.enums import Priority

_DASHES = str.maketrans({char: "-" for char in "‐‑‒–—―−"})
_PRIORITIES = {
    Priority.CRITICAL: {"critical", "blocking", "blocker", "emergency", "immediate"},
    Priority.HIGH: {"high", "urgent", "asap", "important"},
    Priority.MEDIUM: {"medium", "normal", "standard", "regular", "routine", "usual", "default"},
    Priority.LOW: {"low", "minor", "not urgent", "whenever"},
}
_DATE_SIGNAL = re.compile(
    r"(?:\d|\btoday\b|\btomorrow\b|\bnext\b|\bthis\b|\bweek\b|\bmonth\b|"
    r"\bmonday\b|\btuesday\b|\bwednesday\b|\bthursday\b|\bfriday\b|\bsaturday\b|\bsunday\b|"
    r"\bjan(?:uary)?\b|\bfeb(?:ruary)?\b|\bmar(?:ch)?\b|\bapr(?:il)?\b|\bmay\b|"
    r"\bjun(?:e)?\b|\bjul(?:y)?\b|\baug(?:ust)?\b|\bsep(?:tember)?\b|"
    r"\boct(?:ober)?\b|\bnov(?:ember)?\b|\bdec(?:ember)?\b)",
    re.IGNORECASE,
)


def normalize_routing_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).translate(_DASHES).split())


def normalize_priority(value: str | None) -> Priority:
    normalized = normalize_routing_text(value or "").lower().strip(" .,!?")
    for priority, aliases in _PRIORITIES.items():
        if normalized in aliases:
            return priority
    return Priority.MEDIUM


def extract_priority(value: str) -> Priority | None:
    normalized = normalize_routing_text(value).lower()
    for priority, aliases in _PRIORITIES.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in aliases):
            return priority
    return None


def derive_task_title(description: str, supplied: str | None = None) -> str:
    if supplied and supplied.strip():
        return normalize_routing_text(supplied)[:200]
    phrase = re.split(r"[.!?;\n]", normalize_routing_text(description), maxsplit=1)[0]
    words = phrase.split()[:8]
    return (" ".join(words) or "Operational task")[:200]


def parse_due_date(value: str | None, *, now: datetime | None = None) -> date | None:
    if not value or not value.strip():
        return None
    normalized = normalize_routing_text(value)
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        pass
    if not _DATE_SIGNAL.search(normalized):
        return None
    base = now or business_now()
    parsed = parse_natural_date(
        normalized,
        settings={
            "RELATIVE_BASE": base.astimezone(RIYADH).replace(tzinfo=None),
            "TIMEZONE": "Asia/Riyadh",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "DATE_ORDER": "DMY",
            "STRICT_PARSING": False,
        },
    )
    if parsed:
        return parsed.astimezone(RIYADH).date()
    matches = search_dates(normalized, settings={
        "RELATIVE_BASE": base.astimezone(RIYADH).replace(tzinfo=None),
        "TIMEZONE": "Asia/Riyadh", "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future", "DATE_ORDER": "DMY",
    })
    return matches[-1][1].astimezone(RIYADH).date() if matches else None


def refers_to_self(value: str | None) -> bool:
    normalized = normalize_routing_text(value or "").lower().strip(" .,!?")
    return normalized in {"me", "myself", "to me", "to myself", "assign me", "assign myself"}


def clarification_assignee_query(value: str) -> str:
    """Remove an accompanying due-date phrase from an assignee clarification."""
    without_date = re.sub(
        r"\b(?:today|tomorrow|next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b|"
        r"\b\d{1,4}[-/]\d{1,2}[-/]\d{1,4}\b|[,;]",
        " ",
        normalize_routing_text(value),
        flags=re.IGNORECASE,
    )
    query = " ".join(without_date.split()).strip()
    query = re.sub(r"^(?:assign(?:\s+it)?\s+to|for)\s+", "", query, flags=re.IGNORECASE)
    return query.lstrip("@").strip()
