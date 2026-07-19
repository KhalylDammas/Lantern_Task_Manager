"""Notification event types and delivery results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class NotificationEvent(StrEnum):
    WELCOME = "welcome"
    TASK_ASSIGNED = "task_assigned"
    VERIFY_REQUESTED = "verify_requested"
    TASK_REOPENED = "task_reopened"
    TASK_VERIFIED = "task_verified"
    DAILY_SUMMARY = "daily_summary"
    OVERDUE_ASSIGNEE = "overdue_assignee"
    OVERDUE_CREATOR = "overdue_creator"


class DeliveryChannel(StrEnum):
    ACTIVITY = "activity"
    BOT_DM = "bot_dm"


@dataclass
class ChannelResult:
    channel: DeliveryChannel
    ok: bool
    detail: str = ""


@dataclass
class NotificationResult:
    event: NotificationEvent
    recipient_entra_id: str
    idempotency_key: str
    skipped_duplicate: bool = False
    channels: list[ChannelResult] = field(default_factory=list)

    @property
    def any_sent(self) -> bool:
        return any(c.ok for c in self.channels)

    def summary(self) -> str:
        if self.skipped_duplicate:
            return "skipped_duplicate"
        if not self.channels:
            return "no_channels"
        parts = [f"{c.channel.value}={'ok' if c.ok else 'fail'}:{c.detail[:80]}" for c in self.channels]
        return "; ".join(parts)
