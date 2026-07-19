"""Scheduled notification jobs (no Azure Functions required).

Invoked via HTTP cron routes on the F1 App Service, e.g. GitHub Actions schedule (free).
Event-driven notifications (task assign, verify, welcome) run without this module.
"""

from __future__ import annotations

import datetime as dt
import logging

from ltm.domain.business_time import business_today
from ltm.config.artefacts import load_escalation_rules
from ltm.config.settings import Settings, get_settings
from ltm.notifications.service import NotificationService
from ltm.storage.db import session_scope
from ltm.storage.orm import IdempotencyRecord
from ltm.storage.repository import TaskRepository

logger = logging.getLogger(__name__)


def _consume_idempotency(session, key: str) -> bool:
    row = session.get(IdempotencyRecord, key)
    if row is not None:
        return False
    session.add(IdempotencyRecord(key=key, payload="{}"))
    session.flush()
    return True


def _days_overdue(due: dt.date, today: dt.date) -> int:
    return max(0, (today - due).days)


def run_overdue_refresh_and_notify(settings: Settings | None = None) -> dict[str, int]:
    """Refresh overdue flags and notify assignee/creator for overdue in-progress tasks."""
    cfg = settings or get_settings()
    day = business_today()
    day_key = day.isoformat()
    key = f"overdue_refresh:{day_key}"
    stats = {"flags_updated": 0, "overdue_tasks": 0, "notifications": 0, "skipped": 0}

    with session_scope() as session:
        if not _consume_idempotency(session, key):
            stats["skipped"] = 1
            logger.info("Skip duplicate overdue refresh %s", key)
            return stats

        repo = TaskRepository(session)
        stats["flags_updated"] = repo.refresh_overdue_flags()
        overdue_rows = repo.list_overdue_in_progress()
        stats["overdue_tasks"] = len(overdue_rows)

        rules = load_escalation_rules()
        threshold = int(rules.get("overdue_threshold_days", 1))
        escalation_key = f"escalation_scan:{day_key}"
        if not _consume_idempotency(session, escalation_key):
            return stats

        notifier = NotificationService(session, cfg)
        for row in overdue_rows:
            days = _days_overdue(row.due_date, day)
            if days < threshold:
                continue
            try:
                notifier.notify_overdue_assignee(row, days_overdue=days, day=day)
                notifier.notify_overdue_creator(row, days_overdue=days, day=day)
                stats["notifications"] += 2
            except Exception:  # noqa: BLE001
                logger.exception("Overdue notification failed task=%s", row.id)

    return stats


def run_daily_summary(
    settings: Settings | None = None,
    *,
    assignee_entra_id: str | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Send daily open-task summary to each assignee.

    When ``assignee_entra_id`` is set, only that user receives the summary.
    This skips the global daily idempotency lock so a targeted test send does
    not block or consume the scheduled batch run. Pass ``force=True`` to bypass
    per-user notification idempotency (repeat sends the same Riyadh day).
    """
    if force and not assignee_entra_id:
        raise ValueError("force requires assignee_entra_id for a single-user test send")

    cfg = settings or get_settings()
    day = business_today()
    day_key = day.isoformat()
    stats = {"assignees": 0, "sent": 0, "skipped": 0, "test_mode": int(assignee_entra_id is not None)}

    with session_scope() as session:
        if assignee_entra_id is None:
            key = f"daily_summary:{day_key}"
            if not _consume_idempotency(session, key):
                stats["skipped"] = 1
                return stats

        repo = TaskRepository(session)
        notifier = NotificationService(session, cfg)
        assignee_ids = [assignee_entra_id] if assignee_entra_id else repo.distinct_assignees_with_open_tasks()
        stats["assignees"] = len(assignee_ids)

        for target_id in assignee_ids:
            tasks = repo.list_open_for_assignee(target_id)
            if not tasks:
                continue
            display = tasks[0].assigned_to.display_name
            try:
                result = notifier.notify_daily_summary(
                    assignee_entra_id=target_id,
                    assignee_display_name=display,
                    tasks=tasks,
                    day=day,
                    force=force,
                )
                if result.skipped_duplicate:
                    stats["skipped"] += 1
                else:
                    stats["sent"] += 1
            except Exception:  # noqa: BLE001
                logger.exception("Daily summary failed user=%s", target_id)

    return stats


def run_notification_retry(settings: Settings | None = None, *, limit: int = 25) -> dict[str, int]:
    cfg = settings or get_settings()
    with session_scope() as session:
        n = NotificationService(session, cfg).retry_failed_deliveries(limit=limit)
    return {"retried": n}
