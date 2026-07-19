"""Central notification orchestration."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ltm.bot.help_text import welcome_bot_text
from ltm.domain.business_time import business_today
from ltm.domain.models import TaskRecord
from ltm.bot.commands import format_task_list_message
from ltm.cards.builders import (
    manager_verification_card,
    overdue_escalation_card,
    task_assignment_card,
    task_reopened_card,
    task_status_card,
    welcome_card,
)
from ltm.config.settings import Settings
from ltm.notifications.activity_feed import send_activity_notification
from ltm.notifications.bot_delivery import send_bot_dm
from ltm.notifications.events import ChannelResult, DeliveryChannel, NotificationEvent, NotificationResult
from ltm.notifications.recipients import assignee_ref, creator_ref, verifier_ref
from ltm.storage.orm import IdempotencyRecord, NotificationDeliveryORM
from ltm.storage.repository import TaskRepository

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, session: Session, settings: Settings | None = None):
        from ltm.config.settings import get_settings

        self._session = session
        self._settings = settings or get_settings()

    def _try_consume_idempotency(self, key: str) -> bool:
        if self._session.get(IdempotencyRecord, key) is not None:
            return False
        self._session.add(IdempotencyRecord(key=key, payload="{}"))
        self._session.flush()
        return True

    def _log_delivery(
        self,
        *,
        event: NotificationEvent,
        recipient_entra_id: str,
        idempotency_key: str,
        result: NotificationResult,
    ) -> None:
        row = NotificationDeliveryORM(
            idempotency_key=idempotency_key,
            event=event.value,
            recipient_entra_id=recipient_entra_id,
            summary=result.summary()[:500],
            activity_ok=any(c.channel == DeliveryChannel.ACTIVITY and c.ok for c in result.channels),
            bot_dm_ok=any(c.channel == DeliveryChannel.BOT_DM and c.ok for c in result.channels),
            needs_retry=not result.skipped_duplicate and not result.any_sent,
        )
        self._session.add(row)
        self._session.flush()

    def _deliver_hybrid(
        self,
        *,
        event: NotificationEvent,
        idempotency_key: str,
        recipient_entra_id: str,
        recipient_display_name: str,
        activity_type: str,
        preview_text: str,
        bot_text: str,
        adaptive_card_dict: dict | None,
        send_activity: bool = True,
        send_bot: bool = True,
        skip_idempotency: bool = False,
    ) -> NotificationResult:
        if not skip_idempotency and not self._try_consume_idempotency(idempotency_key):
            return NotificationResult(
                event=event,
                recipient_entra_id=recipient_entra_id,
                idempotency_key=idempotency_key,
                skipped_duplicate=True,
            )

        result = NotificationResult(
            event=event,
            recipient_entra_id=recipient_entra_id,
            idempotency_key=idempotency_key,
        )

        if send_activity:
            ok, detail = send_activity_notification(
                self._settings,
                user_entra_id=recipient_entra_id,
                activity_type=activity_type,
                preview_text=preview_text,
            )
            result.channels.append(ChannelResult(channel=DeliveryChannel.ACTIVITY, ok=ok, detail=detail))

        if send_bot:
            ok, detail = send_bot_dm(
                self._settings,
                self._session,
                user_entra_id=recipient_entra_id,
                user_display_name=recipient_display_name,
                text=bot_text,
                adaptive_card_dict=adaptive_card_dict,
            )
            result.channels.append(ChannelResult(channel=DeliveryChannel.BOT_DM, ok=ok, detail=detail))

        self._log_delivery(
            event=event,
            recipient_entra_id=recipient_entra_id,
            idempotency_key=idempotency_key,
            result=result,
        )
        logger.info(
            "Notification %s → %s: %s",
            event.value,
            recipient_entra_id,
            result.summary(),
        )
        return result

    def notify_welcome(self, *, user_entra_id: str, user_display_name: str) -> NotificationResult:
        card = welcome_card()
        card_dict = card.model_dump(by_alias=True, exclude_none=True)
        return self._deliver_hybrid(
            event=NotificationEvent.WELCOME,
            idempotency_key=f"notify:welcome:{user_entra_id}",
            recipient_entra_id=user_entra_id,
            recipient_display_name=user_display_name,
            activity_type="welcome",
            preview_text="Welcome to Lantern Task Manager",
            bot_text=welcome_bot_text(),
            adaptive_card_dict=card_dict,
            send_activity=False,
        )

    def notify_task_assigned(self, task: TaskRecord) -> NotificationResult:
        assignee = assignee_ref(task)
        card = task_assignment_card(
            task_id=task.id,
            task_type=task.task_type,
            description=task.description,
            due=str(task.due_date),
            priority=str(task.priority),
            created_by_name=task.created_by.display_name or task.created_by.entra_object_id,
        )
        card_dict = card.model_dump(by_alias=True, exclude_none=True)
        preview = f"New task {task.id} assigned to you"
        bot_text = f"You were assigned task `{task.id}` ({task.task_type}), due {task.due_date}."
        result = self._deliver_hybrid(
            event=NotificationEvent.TASK_ASSIGNED,
            idempotency_key=f"notify:task_assigned:{task.id}",
            recipient_entra_id=assignee.entra_object_id,
            recipient_display_name=assignee.display_name,
            activity_type="taskAssigned",
            preview_text=preview,
            bot_text=bot_text,
            adaptive_card_dict=card_dict,
        )
        TaskRepository(self._session).append_audit(
            task.id,
            event="NOTIFIED",
            actor_entra_id="SYSTEM",
            details=f"assignee:{result.summary()}",
        )
        return result

    def notify_verify_requested(self, task: TaskRecord, *, completion_notes: str) -> NotificationResult:
        verifier = verifier_ref(task, self._settings)
        summary = "\n".join(filter(None, [completion_notes.strip(), task.description[:500]]))
        card = manager_verification_card(task_id=task.id, summary=summary or task.description[:800])
        card_dict = card.model_dump(by_alias=True, exclude_none=True)
        assignee_name = task.assigned_to.display_name or task.assigned_to.entra_object_id
        preview = f"Verify completion of {task.id} for {assignee_name}"
        return self._deliver_hybrid(
            event=NotificationEvent.VERIFY_REQUESTED,
            idempotency_key=f"notify:verify_requested:{task.id}",
            recipient_entra_id=verifier.entra_object_id,
            recipient_display_name=verifier.display_name,
            activity_type="verifyRequested",
            preview_text=preview,
            bot_text=f"Please verify completion of task `{task.id}`.",
            adaptive_card_dict=card_dict,
        )

    def notify_task_reopened(self, task: TaskRecord, *, reason: str) -> NotificationResult:
        assignee = assignee_ref(task)
        card = task_reopened_card(task_id=task.id, reason=reason)
        card_dict = card.model_dump(by_alias=True, exclude_none=True)
        preview = f"Task {task.id} was reopened"
        return self._deliver_hybrid(
            event=NotificationEvent.TASK_REOPENED,
            idempotency_key=f"notify:task_reopened:{task.id}:{task.updated_at.isoformat()}",
            recipient_entra_id=assignee.entra_object_id,
            recipient_display_name=assignee.display_name,
            activity_type="taskReopened",
            preview_text=preview,
            bot_text=f"Task `{task.id}` was reopened: {reason[:200]}",
            adaptive_card_dict=card_dict,
        )

    def notify_task_verified(self, task: TaskRecord) -> NotificationResult:
        assignee = assignee_ref(task)
        card = task_status_card(task_id=task.id, status="VERIFIED")
        card_dict = card.model_dump(by_alias=True, exclude_none=True)
        preview = f"Task {task.id} verified complete"
        return self._deliver_hybrid(
            event=NotificationEvent.TASK_VERIFIED,
            idempotency_key=f"notify:task_verified:{task.id}",
            recipient_entra_id=assignee.entra_object_id,
            recipient_display_name=assignee.display_name,
            activity_type="taskVerified",
            preview_text=preview,
            bot_text=f"Task `{task.id}` has been verified complete.",
            adaptive_card_dict=card_dict,
            send_bot=False,
        )

    def notify_daily_summary(
        self,
        *,
        assignee_entra_id: str,
        assignee_display_name: str,
        tasks: list[TaskRecord],
        day: date | None = None,
        force: bool = False,
    ) -> NotificationResult:
        day_key = (day or business_today()).isoformat()
        count = len(tasks)
        preview = f"You have {count} open task(s) in LTM"
        bot_text = format_task_list_message(tasks=tasks, variant="daily_summary")
        idempotency_key = f"notify:daily_summary:{day_key}:{assignee_entra_id}"
        if force:
            idempotency_key = f"notify:daily_summary:force:{day_key}:{assignee_entra_id}"
        return self._deliver_hybrid(
            event=NotificationEvent.DAILY_SUMMARY,
            idempotency_key=idempotency_key,
            recipient_entra_id=assignee_entra_id,
            recipient_display_name=assignee_display_name,
            activity_type="dailySummary",
            preview_text=preview,
            bot_text=bot_text,
            adaptive_card_dict=None,
            skip_idempotency=force,
        )

    def notify_overdue_assignee(self, task: TaskRecord, *, days_overdue: int, day: date | None = None) -> NotificationResult:
        assignee = assignee_ref(task)
        day_key = (day or business_today()).isoformat()
        preview = f"Task {task.id} is overdue"
        return self._deliver_hybrid(
            event=NotificationEvent.OVERDUE_ASSIGNEE,
            idempotency_key=f"notify:overdue_assignee:{day_key}:{task.id}",
            recipient_entra_id=assignee.entra_object_id,
            recipient_display_name=assignee.display_name,
            activity_type="taskOverdue",
            preview_text=preview,
            bot_text=f"Task `{task.id}` is overdue (due {task.due_date}).",
            adaptive_card_dict=None,
            send_bot=False,
        )

    def notify_overdue_creator(self, task: TaskRecord, *, days_overdue: int, day: date | None = None) -> NotificationResult:
        creator = creator_ref(task)
        day_key = (day or business_today()).isoformat()
        assignee_name = task.assigned_to.display_name or task.assigned_to.entra_object_id
        card = overdue_escalation_card(
            task_id=task.id,
            assignee_name=assignee_name,
            days_overdue=days_overdue,
        )
        card_dict = card.model_dump(by_alias=True, exclude_none=True)
        preview = f"Overdue: {task.id} for {assignee_name}"
        return self._deliver_hybrid(
            event=NotificationEvent.OVERDUE_CREATOR,
            idempotency_key=f"notify:overdue_creator:{day_key}:{task.id}",
            recipient_entra_id=creator.entra_object_id,
            recipient_display_name=creator.display_name,
            activity_type="taskOverdueEscalation",
            preview_text=preview,
            bot_text=f"LTM escalation: task `{task.id}` is overdue for {assignee_name}.",
            adaptive_card_dict=card_dict,
        )

    def retry_failed_deliveries(self, *, limit: int = 20) -> int:
        """Re-attempt deliveries marked needs_retry (Phase 4 outbox). Returns retry count."""
        rows = (
            self._session.execute(
                select(NotificationDeliveryORM)
                .where(NotificationDeliveryORM.needs_retry.is_(True))
                .order_by(NotificationDeliveryORM.processed_at.asc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        retried = 0
        for row in rows:
            # Clear idempotency so hybrid can re-run with a new key suffix
            retry_key = f"{row.idempotency_key}:retry:{row.id}"
            if self._session.get(IdempotencyRecord, retry_key) is not None:
                row.needs_retry = False
                continue
            ok_act, _ = send_activity_notification(
                self._settings,
                user_entra_id=row.recipient_entra_id,
                activity_type=row.event,
                preview_text=f"LTM reminder ({row.event})",
            )
            ok_bot, _ = send_bot_dm(
                self._settings,
                self._session,
                user_entra_id=row.recipient_entra_id,
                user_display_name="",
                text=f"LTM reminder: {row.event}",
                adaptive_card_dict=None,
            )
            self._session.add(IdempotencyRecord(key=retry_key, payload="{}"))
            row.needs_retry = not (ok_act or ok_bot)
            row.summary = f"retry:activity={ok_act},bot={ok_bot}"
            retried += 1
        self._session.flush()
        return retried
