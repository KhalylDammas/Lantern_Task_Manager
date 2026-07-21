"""Task lifecycle use cases and their transaction boundaries."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from ltm.application.results import UseCaseResult
from ltm.config.settings import Settings, get_settings
from ltm.domain.models import CloseTaskParams, ListTasksParams, TaskRecord, UserRef
from ltm.notifications.recipients import is_verifier, verifier_ref
from ltm.interaction.models import InteractionOrigin
from ltm.notifications.service import NotificationService
from ltm.policy.access import can_view_task
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskUseCases:
    """One transport-neutral entry point for task reads and lifecycle actions."""

    def __init__(self, settings_provider: Callable[[], Settings] = get_settings):
        self._settings_provider = settings_provider

    def list_tasks(self, params: ListTasksParams, actor: UserRef) -> UseCaseResult[list[TaskRecord]]:
        settings = self._settings_provider()
        # Authorize each result centrally before applying the caller's page limit.
        with session_scope() as session:
            candidates = TaskRepository(session).list_tasks(params, actor.entra_object_id, apply_limit=False)
            tasks = [
                task
                for task in candidates
                if can_view_task(actor.entra_object_id, task, settings)
            ][: params.limit]
        return UseCaseResult.success(tasks, code="TASKS_LISTED", message=f"Found {len(tasks)} task(s).")

    def get_task(self, task_id: str, actor: UserRef) -> UseCaseResult[TaskRecord]:
        settings = self._settings_provider()
        with session_scope() as session:
            task = TaskRepository(session).get(task_id)
        if task is None:
            return UseCaseResult.failure(code="NOT_FOUND", message=f"Task {task_id} was not found.")
        if not can_view_task(actor.entra_object_id, task, settings):
            return UseCaseResult.failure(code="NOT_AUTHORIZED", message="You do not have access to this task.")
        return UseCaseResult.success(task, code="TASK_FOUND", message=f"Task {task_id} found.")

    def search_tasks(self, query: str, actor: UserRef, *, limit: int = 10) -> UseCaseResult[list[TaskRecord]]:
        settings = self._settings_provider()
        with session_scope() as session:
            matches = TaskRepository(session).search(query, limit=100)
            tasks = [task for task in matches if can_view_task(actor.entra_object_id, task, settings)][:limit]
        return UseCaseResult.success(tasks, code="TASKS_FOUND", message=f"Found {len(tasks)} task(s).")

    def acknowledge(self, task_id: str, actor: UserRef) -> UseCaseResult[TaskRecord]:
        return self._assignee_transition(
            task_id,
            actor,
            operation="acknowledge",
            transition=lambda repo: repo.assignee_acknowledge(task_id, actor.entra_object_id),
            success_code="TASK_ACKNOWLEDGED",
            success_message=f"Acknowledged: {task_id}. Task is now in progress.",
        )

    def resume(self, task_id: str, actor: UserRef) -> UseCaseResult[TaskRecord]:
        return self._assignee_transition(
            task_id,
            actor,
            operation="resume",
            transition=lambda repo: repo.assignee_resume(task_id, actor.entra_object_id),
            success_code="TASK_RESUMED",
            success_message=f"Resumed: {task_id}. Task is now in progress.",
        )

    async def close(self, params: CloseTaskParams, actor: UserRef,
                    origin: InteractionOrigin | None = None) -> UseCaseResult[TaskRecord]:
        settings = self._settings_provider()
        with session_scope() as session:
            repo = TaskRepository(session)
            task = repo.get(params.task_id)
            denial = self._require_assignee(task, actor, operation="close")
            if denial:
                return denial
            try:
                verifier = verifier_ref(task, settings)
                auto_verify = (
                    settings.self_close_auto_verification_enabled
                    and task.created_by.entra_object_id == actor.entra_object_id
                    and task.assigned_to.entra_object_id == actor.entra_object_id
                    and verifier.entra_object_id == actor.entra_object_id
                )
                closed = (repo.close_and_verify_self(params, actor.entra_object_id) if auto_verify
                          else repo.mark_pending_closure_from_assignee(params, actor.entra_object_id))
            except ValueError as exc:
                return UseCaseResult.failure(code="INVALID_STATUS", message=str(exc))

        if auto_verify:
            result = UseCaseResult.success(closed, code="TASK_VERIFIED_SELF",
                                           message=f"{params.task_id} closed and verified.")
            return await self._notify(
                result, lambda service: service.notify_task_verified(closed, origin=origin))
        result = UseCaseResult.success(closed, code="TASK_CLOSED",
                                       message=f"Submitted {params.task_id} for verification.")
        return await self._notify(
            result,
            lambda service: service.notify_verify_requested(
                closed, completion_notes=params.completion_notes, origin=origin),
        )

    async def verify(self, task_id: str, actor: UserRef) -> UseCaseResult[TaskRecord]:
        settings = self._settings_provider()
        with session_scope() as session:
            repo = TaskRepository(session)
            task = repo.get(task_id)
            denial = self._require_verifier(task, actor, settings)
            if denial:
                return denial
            try:
                verified = repo.manager_confirm(task_id, actor.entra_object_id)
            except ValueError as exc:
                return UseCaseResult.failure(code="INVALID_STATUS", message=str(exc))

        result = UseCaseResult.success(verified, code="TASK_VERIFIED", message=f"{task_id} verified.")
        return await self._notify(result, lambda service: service.notify_task_verified(verified))

    async def reopen(self, task_id: str, reason: str, actor: UserRef) -> UseCaseResult[TaskRecord]:
        settings = self._settings_provider()
        with session_scope() as session:
            repo = TaskRepository(session)
            task = repo.get(task_id)
            denial = self._require_verifier(task, actor, settings)
            if denial:
                return denial
            try:
                reopened = repo.manager_reject(task_id, actor.entra_object_id, reason)
            except ValueError as exc:
                return UseCaseResult.failure(code="INVALID_STATUS", message=str(exc))

        result = UseCaseResult.success(reopened, code="TASK_REOPENED", message=f"{task_id} reopened.")
        return await self._notify(
            result,
            lambda service: service.notify_task_reopened(reopened, reason=reason),
        )

    def _assignee_transition(
        self,
        task_id: str,
        actor: UserRef,
        *,
        operation: str,
        transition: Callable[[TaskRepository], TaskRecord],
        success_code: str,
        success_message: str,
    ) -> UseCaseResult[TaskRecord]:
        with session_scope() as session:
            repo = TaskRepository(session)
            task = repo.get(task_id)
            denial = self._require_assignee(task, actor, operation=operation)
            if denial:
                return denial
            try:
                changed = transition(repo)
            except ValueError as exc:
                return UseCaseResult.failure(code="INVALID_STATUS", message=str(exc))
        return UseCaseResult.success(changed, code=success_code, message=success_message)

    @staticmethod
    def _require_assignee(
        task: TaskRecord | None,
        actor: UserRef,
        *,
        operation: str,
    ) -> UseCaseResult[TaskRecord] | None:
        if task is None:
            return UseCaseResult.failure(code="NOT_FOUND", message="Task not found.")
        if task.assigned_to.entra_object_id != actor.entra_object_id:
            return UseCaseResult.failure(
                code="NOT_ASSIGNEE",
                message=f"Only the assignee can {operation} this task.",
            )
        return None

    @staticmethod
    def _require_verifier(
        task: TaskRecord | None,
        actor: UserRef,
        settings: Settings,
    ) -> UseCaseResult[TaskRecord] | None:
        if task is None:
            return UseCaseResult.failure(code="NOT_FOUND", message="Task not found.")
        if not is_verifier(actor.entra_object_id, task, settings):
            return UseCaseResult.failure(
                code="NOT_VERIFIER",
                message="You are not the configured verifier for this task.",
            )
        return None

    async def _notify(
        self,
        result: UseCaseResult[TaskRecord],
        send: Callable[[NotificationService], object],
    ) -> UseCaseResult[TaskRecord]:
        def deliver() -> None:
            with session_scope() as session:
                send(NotificationService(session, self._settings_provider()))

        try:
            await asyncio.to_thread(deliver)
        except Exception:  # noqa: BLE001
            task_id = result.value.id if result.value else "unknown"
            logger.exception("Post-commit notification failed for task %s", task_id)
            return result.with_warning("The task was updated, but its notification could not be delivered.")
        return result
