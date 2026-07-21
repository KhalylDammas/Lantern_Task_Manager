"""LLM tool bindings → domain + D365 (LTM_SYSTEM_SPEC §10)."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator
from microsoft_teams.ai import Function

from ltm.application import DraftUseCases, TaskUseCases, UseCaseResult
from ltm.bot.context import get_actor, push_pending_card, set_terminal_response
from ltm.bot.d365_tools import build_d365_functions
from ltm.policy import AssignmentPolicyError, assert_assignee_department_matches, assert_can_assign, tool_error
from ltm.bot.drafts import stash_draft
from ltm.bot.commands import format_task_list_message
from ltm.cards.builders import draft_confirm_card, task_detail_card
from ltm.domain.enums import DeptCode, Priority
from ltm.domain.models import (
    AcknowledgeTaskParams,
    CloseTaskParams,
    D365References,
    DraftActionParams,
    GetTaskParams,
    ListTasksParams,
    ReopenTaskParams,
    ResumeTaskParams,
    TaskCreateDraft,
    VerifyTaskParams,
)

logger = logging.getLogger(__name__)


class CreateTaskToolParams(BaseModel):
    task_type: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=8000)
    assignee_entra_id: str = Field(min_length=1)
    assignee_display_name: str = ""
    assignee_department: str = ""
    assignee_department_code: DeptCode
    priority: Priority = Priority.MEDIUM
    due_date: str
    purchase_order_number: str | None = None
    vendor_account: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    customer_account: str | None = None
    project_id: str | None = None

    @field_validator("due_date")
    @classmethod
    def check_iso_date(cls, v: str) -> str:
        date.fromisoformat(v)
        return v


async def create_task_handler(params: CreateTaskToolParams) -> str:
    actor = get_actor()
    try:
        assert_assignee_department_matches(
            assignee_entra_id=params.assignee_entra_id,
            assignee_department_code=params.assignee_department_code,
        )
        assert_can_assign(
            requester_entra_id=actor.entra_object_id,
            assignee_entra_id=params.assignee_entra_id,
        )
    except AssignmentPolicyError as exc:
        logger.warning(
            "Task draft denied by assignment policy: requester_entra_id=%s assignee_entra_id=%s "
            "assignee_department_code=%s error_type=%s message=%r",
            actor.entra_object_id,
            params.assignee_entra_id,
            params.assignee_department_code.value,
            type(exc).__name__,
            exc.user_message,
        )
        set_terminal_response(exc.user_message)
        return exc.user_message

    d365 = D365References(
        purchase_order_number=params.purchase_order_number,
        vendor_account=params.vendor_account,
        vendor_name=params.vendor_name,
        invoice_number=params.invoice_number,
        customer_account=params.customer_account,
        project_id=params.project_id,
    )
    draft = TaskCreateDraft(
        task_type=params.task_type,
        description=params.description,
        assignee_entra_id=params.assignee_entra_id,
        assignee_display_name=params.assignee_display_name,
        assignee_department=params.assignee_department,
        assignee_department_code=params.assignee_department_code,
        priority=params.priority,
        due_date=date.fromisoformat(params.due_date),
        d365=d365,
    )
    draft_id = stash_draft(draft, actor.entra_object_id)
    card = draft_confirm_card(
        draft_id=draft_id,
        task_type=draft.task_type,
        assignee=f"{draft.assignee_display_name or draft.assignee_entra_id} ({draft.assignee_department_code.value})",
        due=str(draft.due_date),
        priority=str(draft.priority),
        description=draft.description,
        po=draft.d365.purchase_order_number,
        assignee_department=draft.assignee_department or draft.assignee_department_code.value,
    )
    push_pending_card(card)
    result = (
        f"Draft {draft_id} prepared. A confirmation card will be shown in Teams. "
        f"Assignee {draft.assignee_display_name or draft.assignee_entra_id}, due {draft.due_date}."
    )
    set_terminal_response(result)
    return result


class EmptyParams(BaseModel):
    """No-op params for tooling smoke tests."""

    _: str | None = None


async def list_tasks_handler(params: ListTasksParams) -> str:
    actor = get_actor()
    result = TaskUseCases().list_tasks(params, actor)
    response = format_task_list_message(tasks=result.value or [], variant=params.filter)
    set_terminal_response(response)
    return response


def _task_result_json(result: UseCaseResult[Any]) -> str:
    """Compact tool-memory result; presentation is handled deterministically."""
    return json.dumps(
        {
            "ok": result.ok,
            "code": result.code,
            "message": result.message,
            "warnings": list(result.warnings),
        },
        default=str,
    )


def _terminal_task_result(result: UseCaseResult[Any]) -> str:
    message = result.message
    if result.warnings:
        message = f"{message} {' '.join(result.warnings)}"
    set_terminal_response(message)
    return _task_result_json(result)


def _push_task_detail(task: Any) -> None:
    push_pending_card(
        task_detail_card(
            task_id=task.id,
            task_type=task.task_type,
            status=str(task.status),
            due=str(task.due_date),
            priority=str(task.priority),
            assignee_name=task.assigned_to.display_name or task.assigned_to.entra_object_id,
            created_by_name=task.created_by.display_name or task.created_by.entra_object_id,
            description=task.description,
        )
    )


def _terminal_task_lookup(result: UseCaseResult[Any]) -> str:
    if not result.ok:
        return _terminal_task_result(result)
    if isinstance(result.value, list):
        response = format_task_list_message(tasks=result.value, variant="department")
    else:
        _push_task_detail(result.value)
        response = result.message
    set_terminal_response(response)
    return json.dumps({"ok": True, "code": result.code, "message": response})


async def acknowledge_task_handler(params: AcknowledgeTaskParams) -> str:
    actor = get_actor()
    return _terminal_task_result(TaskUseCases().acknowledge(params.task_id, actor))


async def confirm_task_draft_handler(params: DraftActionParams) -> str:
    return _terminal_task_result(await DraftUseCases().confirm(params.draft_id, get_actor()))


async def cancel_task_draft_handler(params: DraftActionParams) -> str:
    return _terminal_task_result(DraftUseCases().cancel(params.draft_id, get_actor()))


async def close_task_handler(params: CloseTaskParams) -> str:
    actor = get_actor()
    return _terminal_task_result(await TaskUseCases().close(params, actor))


async def reopen_task_handler(params: ReopenTaskParams) -> str:
    actor = get_actor()
    return _terminal_task_result(await TaskUseCases().reopen(params.task_id, params.reason, actor))


async def verify_task_handler(params: VerifyTaskParams) -> str:
    return _terminal_task_result(await TaskUseCases().verify(params.task_id, get_actor()))


async def resume_task_handler(params: ResumeTaskParams) -> str:
    actor = get_actor()
    return _terminal_task_result(TaskUseCases().resume(params.task_id, actor))


async def get_task_handler(params: GetTaskParams) -> str:
    actor = get_actor()
    if params.task_id:
        return _terminal_task_lookup(TaskUseCases().get_task(params.task_id, actor))
    if params.query:
        return _terminal_task_lookup(TaskUseCases().search_tasks(params.query, actor))
    message = "Provide a task id or search query."
    set_terminal_response(message)
    return tool_error("TASK_ID_OR_QUERY_REQUIRED", message)


def build_functions() -> list[Function[Any]]:
    lifecycle_functions = [
        Function[CreateTaskToolParams](
            name="create_task",
            description=(
                "Propose a task (does not persist until user confirms the Adaptive Card). "
                "Call immediately when task_type, description, assignee_entra_id, assignee_department_code, "
                "due_date, and priority are known; the user may confirm by card or explicitly in chat. "
                "Use enrichments.mentions.resolved in the turn JSON when present; do not ask for an ID already provided. "
                "If enrichments.mentions.ambiguous is non-empty, wait for the host picker card or user choice before calling. "
                "Needs assignee_entra_id, dept code FIN|PROC|PROJ|HR|IT|CEO, due_date ISO yyyy-mm-dd."
            ),
            parameter_schema=CreateTaskToolParams,
            handler=create_task_handler,
        ),
        Function[ListTasksParams](
            name="list_tasks",
            description=(
                "List tasks with filter exactly one of: my_tasks (assigned to actor.entra_object_id from the turn envelope), "
                "my_requests (tasks created by the actor), department, "
                "all_overdue, pending_verification. Use my_tasks when the user asks for tasks assigned to them."
            ),
            parameter_schema=ListTasksParams,
            handler=list_tasks_handler,
        ),
        Function[CloseTaskParams](
            name="close_task",
            description=(
                "Assignee closes with completion_notes → pending verification. "
                "Use task_id from enrichments.task_references or the user message. "
                "Only the assignee can close (enforced server-side from turn actor)."
            ),
            parameter_schema=CloseTaskParams,
            handler=close_task_handler,
        ),
        Function[AcknowledgeTaskParams](
            name="acknowledge_task",
            description=(
                "Assignee acknowledges an ASSIGNED task -> IN_PROGRESS. "
                "Use task_id from enrichments.task_references or the user message. "
                "This is the chat fallback when the assignment card was not received."
            ),
            parameter_schema=AcknowledgeTaskParams,
            handler=acknowledge_task_handler,
        ),
        Function[DraftActionParams](
            name="confirm_task_draft",
            description="Confirm and create a prepared task draft. Use the draft_id returned by create_task.",
            parameter_schema=DraftActionParams,
            handler=confirm_task_draft_handler,
        ),
        Function[DraftActionParams](
            name="cancel_task_draft",
            description="Cancel a prepared task draft. Use the draft_id returned by create_task.",
            parameter_schema=DraftActionParams,
            handler=cancel_task_draft_handler,
        ),
        Function[ReopenTaskParams](
            name="reopen_task",
            description=(
                "Verifier sends a pending-verification task back for more work → REOPENED with a required reason. "
                "Only the task's configured verifier may reopen (enforced server-side from the turn actor); "
                "returns a structured error otherwise. Use task_id from enrichments.task_references or the message."
            ),
            parameter_schema=ReopenTaskParams,
            handler=reopen_task_handler,
        ),
        Function[VerifyTaskParams](
            name="verify_task",
            description=(
                "Configured verifier confirms a pending-verification task as complete. "
                "Authorization is enforced server-side."
            ),
            parameter_schema=VerifyTaskParams,
            handler=verify_task_handler,
        ),
        Function[ResumeTaskParams](
            name="resume_task",
            description=(
                "Assignee resumes a REOPENED task → IN_PROGRESS. "
                "Only the assignee may resume (enforced server-side); returns a structured error otherwise. "
                "Use task_id from enrichments.task_references or the message."
            ),
            parameter_schema=ResumeTaskParams,
            handler=resume_task_handler,
        ),
        Function[GetTaskParams](
            name="get_task_status",
            description=(
                "Fetch task by LTM id (from enrichments.task_references or message) or keyword search."
            ),
            parameter_schema=GetTaskParams,
            handler=get_task_handler,
        ),
    ]
    return lifecycle_functions + build_d365_functions()


_GROQ_CHAT_TOOL_NAMES = frozenset(
    {
        "create_task",
        "list_tasks",
        "acknowledge_task",
        "confirm_task_draft",
        "cancel_task_draft",
        "close_task",
        "verify_task",
        "reopen_task",
        "resume_task",
        "get_task_status",
    }
)


def build_functions_for_groq_chat() -> list[Function[Any]]:
    """Legacy 4-tool subset; prefer LLM_TOOL_PROFILE=full for D365 lookups."""
    return [f for f in build_functions() if f.name in _GROQ_CHAT_TOOL_NAMES]
