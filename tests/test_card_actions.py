from __future__ import annotations

from datetime import date, timedelta

import pytest

from ltm.bot.card_actions import dispatch_card_action
from ltm.cards.builders import draft_confirm_payload, task_assignment_card
from ltm.domain.enums import DeptCode, Priority, TaskStatus
from ltm.domain.models import TaskCreateDraft, UserRef
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository


def _assigned_task() -> tuple[str, UserRef]:
    creator = UserRef(entra_object_id="creator")
    assignee = UserRef(entra_object_id="assignee")
    draft = TaskCreateDraft(
        task_type="Card routing",
        description="Test canonical and legacy verbs",
        assignee_entra_id=assignee.entra_object_id,
        assignee_department_code=DeptCode.IT,
        priority=Priority.MEDIUM,
        due_date=date.today() + timedelta(days=1),
    )
    with session_scope() as session:
        task = TaskRepository(session).create_from_draft(draft, creator)
    return task.id, assignee


@pytest.mark.asyncio
async def test_canonical_task_action_routes_to_shared_use_case() -> None:
    task_id, assignee = _assigned_task()
    dispatched = await dispatch_card_action("task.acknowledge", {"task_id": task_id}, assignee)

    assert dispatched.handled
    assert dispatched.result is not None and dispatched.result.ok
    assert dispatched.result.value.status == TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_legacy_card_verb_remains_compatible() -> None:
    task_id, assignee = _assigned_task()
    dispatched = await dispatch_card_action("ack_task", {"task_id": task_id}, assignee)

    assert dispatched.handled
    assert dispatched.result is not None
    assert dispatched.result.code == "TASK_ACKNOWLEDGED"


@pytest.mark.asyncio
async def test_close_card_has_chat_parity_and_recovers_missed_acknowledgement(monkeypatch) -> None:
    task_id, assignee = _assigned_task()
    monkeypatch.setattr(
        "ltm.notifications.service.NotificationService.notify_verify_requested",
        lambda *args, **kwargs: None,
    )

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("ltm.application.tasks.asyncio.to_thread", run_inline)

    dispatched = await dispatch_card_action(
        "task.close",
        {"task_id": task_id, "completion_notes": "Completed from the assignment card"},
        assignee,
    )

    assert dispatched.handled
    assert dispatched.result is not None and dispatched.result.ok
    assert dispatched.result.value.status == TaskStatus.PENDING_VERIFICATION


@pytest.mark.asyncio
async def test_unknown_card_action_is_not_consumed() -> None:
    dispatched = await dispatch_card_action("unrelated", {}, UserRef(entra_object_id="actor"))
    assert not dispatched.handled


def test_completion_notes_input_is_on_assignment_not_draft_card() -> None:
    draft = draft_confirm_payload(
        draft_id="draft-1",
        task_type="Review",
        assignee="Assignee",
        due="2026-07-21",
        priority="Medium",
        description="Review task",
    )
    assignment = task_assignment_card(
        task_id="LTM-IT-2026-0001",
        task_type="Review",
        description="Review task",
        due="2026-07-21",
        priority="Medium",
        created_by_name="Creator",
    ).model_dump(by_alias=True, exclude_none=True)

    assert not any(item.get("id") == "completion_notes" for item in draft["body"])
    assert any(item.get("id") == "completion_notes" for item in assignment["body"])
