"""Confirmed-draft use cases shared by cards and chat tools."""

from __future__ import annotations

import asyncio
import logging

from ltm.application.results import UseCaseResult
from ltm.bot.drafts import (
    DraftAccessError,
    completed_draft_task_id,
    discard_draft,
    peek_draft,
    record_draft_task_id,
    take_draft_in_session,
)
from ltm.config.settings import get_settings
from ltm.domain.models import TaskRecord, UserRef
from ltm.notifications.service import NotificationService
from ltm.interaction.models import InteractionOrigin
from ltm.policy import AssignmentPolicyError, assert_assignee_department_matches, assert_can_assign
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository

logger = logging.getLogger(__name__)


class DraftUseCases:
    async def confirm(self, draft_id: str, actor: UserRef,
                      origin: InteractionOrigin | None = None) -> UseCaseResult[TaskRecord]:
        try:
            draft = peek_draft(draft_id, actor.entra_object_id)
        except DraftAccessError as exc:
            return UseCaseResult.failure(code="NOT_DRAFT_REQUESTER", message=str(exc))
        if draft is None:
            try:
                completed_task_id = completed_draft_task_id(draft_id, actor.entra_object_id)
            except DraftAccessError as exc:
                return UseCaseResult.failure(code="NOT_DRAFT_REQUESTER", message=str(exc))
            if completed_task_id:
                with session_scope() as session:
                    completed_task = TaskRepository(session).get(completed_task_id)
                if completed_task is not None:
                    return UseCaseResult.success(
                        completed_task, code="TASK_CREATED",
                        message=f"Task created: {completed_task.id}")
            return UseCaseResult.failure(code="DRAFT_EXPIRED", message="Draft expired or already confirmed.")

        try:
            assert_assignee_department_matches(
                assignee_entra_id=draft.assignee_entra_id,
                assignee_department_code=draft.assignee_department_code,
            )
            assert_can_assign(
                requester_entra_id=actor.entra_object_id,
                assignee_entra_id=draft.assignee_entra_id,
            )
        except AssignmentPolicyError as exc:
            return UseCaseResult.failure(code="ASSIGNMENT_DENIED", message=exc.user_message)

        try:
            with session_scope() as session:
                claimed = take_draft_in_session(session, draft_id, actor.entra_object_id)
                if claimed is None:
                    return UseCaseResult.failure(
                        code="DRAFT_EXPIRED", message="Draft expired or already confirmed.")
                task = TaskRepository(session).create_from_draft(claimed, actor)
                record_draft_task_id(session, draft_id, task.id)
        except DraftAccessError as exc:
            return UseCaseResult.failure(code="NOT_DRAFT_REQUESTER", message=str(exc))

        result = UseCaseResult.success(task, code="TASK_CREATED", message=f"Task created: {task.id}")
        def notify() -> None:
            with session_scope() as session:
                NotificationService(session, get_settings()).notify_task_assigned(
                    task, origin=origin or InteractionOrigin(actor_entra_id=actor.entra_object_id))

        try:
            await asyncio.to_thread(notify)
        except Exception:  # noqa: BLE001
            logger.exception("Assignee notification failed for task %s", task.id)
            return result.with_warning("The task was created, but the assignee notification could not be delivered.")
        return result

    @staticmethod
    def cancel(draft_id: str, actor: UserRef) -> UseCaseResult[str]:
        try:
            found = discard_draft(draft_id, actor.entra_object_id)
        except DraftAccessError as exc:
            return UseCaseResult.failure(code="NOT_DRAFT_REQUESTER", message=str(exc))
        if not found:
            return UseCaseResult.failure(code="DRAFT_EXPIRED", message="Draft expired or already cancelled.")
        return UseCaseResult.success(draft_id, code="DRAFT_CANCELLED", message="Draft cancelled.")
