from __future__ import annotations

from datetime import date, timedelta

import pytest

from ltm.application.tasks import TaskUseCases
from ltm.domain.enums import DeptCode, Priority, TaskStatus
from ltm.domain.models import CloseTaskParams, ListTasksParams, TaskCreateDraft, UserRef
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository


def _create_task() -> tuple[str, UserRef, UserRef]:
    creator = UserRef(entra_object_id="creator", display_name="Creator", department="IT")
    assignee = UserRef(entra_object_id="assignee", display_name="Assignee", department="IT")
    draft = TaskCreateDraft(
        task_type="Maintainability test",
        description="Exercise the shared lifecycle use cases",
        assignee_entra_id=assignee.entra_object_id,
        assignee_display_name=assignee.display_name,
        assignee_department=assignee.department,
        assignee_department_code=DeptCode.IT,
        priority=Priority.MEDIUM,
        due_date=date.today() + timedelta(days=1),
    )
    with session_scope() as session:
        task = TaskRepository(session).create_from_draft(draft, creator)
    return task.id, creator, assignee


def test_acknowledge_has_transport_neutral_success_and_denial() -> None:
    task_id, _, assignee = _create_task()
    use_cases = TaskUseCases()

    denied = use_cases.acknowledge(task_id, UserRef(entra_object_id="stranger"))
    assert not denied.ok
    assert denied.code == "NOT_ASSIGNEE"

    acknowledged = use_cases.acknowledge(task_id, assignee)
    assert acknowledged.ok
    assert acknowledged.code == "TASK_ACKNOWLEDGED"
    assert acknowledged.value is not None
    assert acknowledged.value.status == TaskStatus.IN_PROGRESS


def test_broad_task_lists_still_enforce_per_task_read_access() -> None:
    task_id, creator, _ = _create_task()
    params = ListTasksParams(filter="department", department="IT")

    denied = TaskUseCases().list_tasks(params, UserRef(entra_object_id="stranger"))
    allowed = TaskUseCases().list_tasks(params, creator)

    assert denied.ok and denied.value == []
    assert allowed.ok and [task.id for task in allowed.value] == [task_id]


@pytest.mark.asyncio
async def test_close_recovers_missed_acknowledgement_and_survives_notification_failure(monkeypatch) -> None:
    task_id, _, assignee = _create_task()
    use_cases = TaskUseCases()

    def fail_notification(*args, **kwargs):
        raise RuntimeError("notification unavailable")

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("ltm.notifications.service.NotificationService.notify_verify_requested", fail_notification)
    monkeypatch.setattr("ltm.application.tasks.asyncio.to_thread", run_inline)
    result = await use_cases.close(
        CloseTaskParams(task_id=task_id, completion_notes="Done"),
        assignee,
    )

    assert result.ok
    assert result.value is not None
    assert result.value.status == TaskStatus.PENDING_VERIFICATION
    assert result.warnings
    assert TaskUseCases().get_task(task_id, assignee).value.status == TaskStatus.PENDING_VERIFICATION
