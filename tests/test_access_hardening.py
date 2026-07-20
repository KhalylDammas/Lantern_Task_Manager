from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from ltm.bot.context import set_turn_context
from ltm.bot.drafts import peek_draft, stash_draft, take_draft
from ltm.bot.tools import GetTaskParams, get_task_handler
from ltm.application.drafts import DraftUseCases
from ltm.domain.enums import DeptCode, Priority
from ltm.domain.models import TaskCreateDraft, UserRef
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository


def _draft() -> TaskCreateDraft:
    return TaskCreateDraft(
        task_type="Demo approval",
        description="Approve the demo request",
        assignee_entra_id="assignee",
        assignee_display_name="Assignee",
        assignee_department="IT",
        assignee_department_code=DeptCode.IT,
        priority=Priority.HIGH,
        due_date=date.today() + timedelta(days=1),
    )


def _create_task() -> str:
    with session_scope() as session:
        task = TaskRepository(session).create_from_draft(
            _draft(),
            UserRef(entra_object_id="creator", display_name="Creator", department="IT"),
        )
        return task.id


@pytest.mark.asyncio
async def test_get_task_allows_participant_and_denies_unrelated_user() -> None:
    task_id = _create_task()
    set_turn_context(conversation_id="c1", actor=UserRef(entra_object_id="creator"))
    allowed = json.loads(await get_task_handler(GetTaskParams(task_id=task_id)))
    assert allowed["ok"] is True
    assert allowed["value"]["id"] == task_id

    set_turn_context(conversation_id="c2", actor=UserRef(entra_object_id="stranger"))
    denied = json.loads(await get_task_handler(GetTaskParams(task_id=task_id)))
    assert denied["code"] == "NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_get_task_allows_configured_ceo_oversight() -> None:
    task_id = _create_task()
    set_turn_context(
        conversation_id="ceo",
        actor=UserRef(entra_object_id="d5b03abf-9013-49af-b7ee-890567cc792d"),
    )
    result = json.loads(await get_task_handler(GetTaskParams(task_id=task_id)))
    assert result["ok"] is True
    assert result["value"]["id"] == task_id


def test_drafts_are_one_time_use() -> None:
    requester_id = "creator"
    draft_id = stash_draft(_draft(), requester_id)
    assert peek_draft(draft_id, requester_id) is not None
    assert take_draft(draft_id, requester_id) is not None
    assert take_draft(draft_id, requester_id) is None


@pytest.mark.asyncio
async def test_draft_cannot_be_confirmed_or_cancelled_by_another_user() -> None:
    requester = UserRef(entra_object_id="creator")
    intruder = UserRef(entra_object_id="intruder")
    draft_id = stash_draft(_draft(), requester.entra_object_id)

    denied_confirm = await DraftUseCases().confirm(draft_id, intruder)
    denied_cancel = DraftUseCases().cancel(draft_id, intruder)

    assert denied_confirm.code == "NOT_DRAFT_REQUESTER"
    assert denied_cancel.code == "NOT_DRAFT_REQUESTER"
    assert peek_draft(draft_id, requester.entra_object_id) is not None
