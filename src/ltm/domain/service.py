"""Application facade over repositories (transactions per call)."""

from __future__ import annotations

from ltm.domain.models import CloseTaskParams, ListTasksParams, TaskCreateDraft, TaskRecord, UserRef
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository


class TaskApplicationService:
    """Use one instance per logical operation boundary."""

    def create_confirmed(self, draft: TaskCreateDraft, requester: UserRef) -> TaskRecord:
        with session_scope() as s:
            repo = TaskRepository(s)
            return repo.create_from_draft(draft, requester)

    def list_tasks(self, params: ListTasksParams, viewer: UserRef) -> list[TaskRecord]:
        with session_scope() as s:
            repo = TaskRepository(s)
            return list(repo.list_tasks(params, viewer.entra_object_id))

    def get_task(self, task_id: str | None, q: str | None) -> list[TaskRecord]:
        with session_scope() as s:
            repo = TaskRepository(s)
            if task_id:
                row = repo.get(task_id)
                return [row] if row else []
            if q:
                return list(repo.search(q))
            return []

    def acknowledge_task(self, task_id: str, assignee: UserRef) -> TaskRecord:
        with session_scope() as s:
            repo = TaskRepository(s)
            return repo.assignee_acknowledge(task_id, assignee.entra_object_id)

    def resume_task(self, task_id: str, assignee: UserRef) -> TaskRecord:
        with session_scope() as s:
            repo = TaskRepository(s)
            return repo.assignee_resume(task_id, assignee.entra_object_id)

    def close_task(self, params: CloseTaskParams, assignee: UserRef) -> TaskRecord:
        with session_scope() as s:
            repo = TaskRepository(s)
            return repo.mark_pending_closure_from_assignee(params, assignee.entra_object_id)

    def manager_confirm(self, task_id: str, manager_entra_id: str) -> TaskRecord:
        with session_scope() as s:
            repo = TaskRepository(s)
            return repo.manager_confirm(task_id, manager_entra_id)

    def manager_reject(self, task_id: str, manager_entra_id: str, reason: str) -> TaskRecord:
        with session_scope() as s:
            repo = TaskRepository(s)
            return repo.manager_reject(task_id, manager_entra_id, reason)
