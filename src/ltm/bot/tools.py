"""LLM tool bindings → domain + D365 (LTM_SYSTEM_SPEC §10)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator
from microsoft_teams.ai import Function

from ltm.bot.context import get_actor, push_pending_card
from ltm.policy import AssignmentPolicyError, assert_assignee_department_matches, assert_can_assign, tool_error
from ltm.policy.access import can_view_task
from ltm.bot.drafts import stash_draft
from ltm.bot.commands import format_task_list_message
from ltm.cards.builders import draft_confirm_card
from ltm.domain.enums import DeptCode, Priority
from ltm.domain.models import (
    CloseTaskParams,
    D365References,
    GetTaskParams,
    ListTasksParams,
    ReopenTaskParams,
    ResumeTaskParams,
    TaskCreateDraft,
)
from ltm.d365.facade import D365Facade
from ltm.notifications.recipients import is_verifier
from ltm.notifications.service import NotificationService
from ltm.config.settings import get_settings
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository

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
    draft_id = stash_draft(draft)
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
    return (
        f"Draft {draft_id} prepared. A confirmation card will be shown in Teams. "
        f"Assignee {draft.assignee_display_name or draft.assignee_entra_id}, due {draft.due_date}."
    )


class EmptyParams(BaseModel):
    """No-op params for tooling smoke tests."""

    _: str | None = None


async def list_tasks_handler(params: ListTasksParams) -> str:
    actor = get_actor()
    with session_scope() as session:
        repo = TaskRepository(session)
        rows = list(repo.list_tasks(params, actor.entra_object_id))
    return format_task_list_message(tasks=rows, variant=params.filter)


async def close_task_handler(params: CloseTaskParams) -> str:
    actor = get_actor()
    settings = get_settings()
    with session_scope() as session:
        repo = TaskRepository(session)
        task = repo.get(params.task_id)
        if task is None:
            return tool_error("NOT_FOUND", f"Task {params.task_id} was not found.")
        if task.assigned_to.entra_object_id != actor.entra_object_id:
            return tool_error("NOT_ASSIGNEE", "Only the assignee can close this task.")
        try:
            rec = repo.mark_pending_closure_from_assignee(params, actor.entra_object_id)
        except ValueError as exc:
            return tool_error("INVALID_STATUS", str(exc))
        try:
            await asyncio.to_thread(
                NotificationService(session, settings).notify_verify_requested,
                rec,
                completion_notes=params.completion_notes,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Verifier notification failed for task %s", rec.id)

    return json.dumps(rec.model_dump(mode="json"), default=str)


async def reopen_task_handler(params: ReopenTaskParams) -> str:
    actor = get_actor()
    settings = get_settings()
    with session_scope() as session:
        repo = TaskRepository(session)
        task = repo.get(params.task_id)
        if task is None:
            return tool_error("NOT_FOUND", f"Task {params.task_id} was not found.")
        if not is_verifier(actor.entra_object_id, task, settings):
            return tool_error("NOT_VERIFIER", "Only the configured verifier can reopen this task.")
        try:
            rec = repo.manager_reject(params.task_id, actor.entra_object_id, params.reason)
        except ValueError as exc:
            return tool_error("INVALID_STATUS", str(exc))
        try:
            await asyncio.to_thread(
                NotificationService(session, settings).notify_task_reopened,
                rec,
                reason=params.reason,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Reopened notification failed for task %s", rec.id)

    return json.dumps(rec.model_dump(mode="json"), default=str)


async def resume_task_handler(params: ResumeTaskParams) -> str:
    actor = get_actor()
    with session_scope() as session:
        repo = TaskRepository(session)
        task = repo.get(params.task_id)
        if task is None:
            return tool_error("NOT_FOUND", f"Task {params.task_id} was not found.")
        if task.assigned_to.entra_object_id != actor.entra_object_id:
            return tool_error("NOT_ASSIGNEE", "Only the assignee can resume this task.")
        try:
            rec = repo.assignee_resume(params.task_id, actor.entra_object_id)
        except ValueError as exc:
            return tool_error("INVALID_STATUS", str(exc))

    return json.dumps(rec.model_dump(mode="json"), default=str)


async def get_task_handler(params: GetTaskParams) -> str:
    actor = get_actor()
    settings = get_settings()
    with session_scope() as session:
        repo = TaskRepository(session)
        if params.task_id:
            row = repo.get(params.task_id)
            if row is None:
                return tool_error("NOT_FOUND", f"Task {params.task_id} was not found.")
            if not can_view_task(actor.entra_object_id, row, settings):
                return tool_error("NOT_AUTHORIZED", "You do not have access to this task.")
            return json.dumps(row.model_dump(mode="json"), default=str)
        if params.query:
            rows = [
                row
                for row in repo.search(params.query, limit=100)
                if can_view_task(actor.entra_object_id, row, settings)
            ][:10]
            return json.dumps([r.model_dump(mode="json") for r in rows], default=str)
        return '{"error":"task_id_or_query_required"}'


def _facade() -> D365Facade:
    return D365Facade(get_settings())


def _log_d365_tool_result(tool_name: str, params: BaseModel, result: str) -> str:
    """Return D365 output unchanged without putting business data in logs."""
    logger.info(
        "D365 tool completed: tool=%s parameter_fields=%s result_length=%s",
        tool_name,
        sorted(params.model_fields_set),
        len(result),
    )
    return result


class POParams(BaseModel):
    po_number: str


async def query_d365_po_handler(params: POParams) -> str:
    result = await _facade().lookup_purchase_order(params.po_number)
    return _log_d365_tool_result("query_d365_po", params, result)


class VendorParams(BaseModel):
    account_or_name: str


async def query_d365_vendor_handler(params: VendorParams) -> str:
    result = await _facade().lookup_vendor(params.account_or_name)
    return _log_d365_tool_result("query_d365_vendor", params, result)


class CustomerParams(BaseModel):
    account_or_name: str


async def query_d365_customer_handler(params: CustomerParams) -> str:
    result = await _facade().lookup_customer(params.account_or_name)
    return _log_d365_tool_result("query_d365_customer", params, result)


class APInvParams(BaseModel):
    invoice_number: str


async def query_d365_invoice_ap_handler(params: APInvParams) -> str:
    result = await _facade().lookup_invoice_ap(params.invoice_number)
    return _log_d365_tool_result("query_d365_invoice_ap", params, result)


class ARInvParams(BaseModel):
    invoice_number: str


async def query_d365_invoice_ar_handler(params: ARInvParams) -> str:
    result = await _facade().lookup_invoice_ar(params.invoice_number)
    return _log_d365_tool_result("query_d365_invoice_ar", params, result)


class EmpParams(BaseModel):
    query: str


async def query_d365_employee_handler(params: EmpParams) -> str:
    result = await _facade().lookup_employee(params.query)
    return _log_d365_tool_result("query_d365_employee", params, result)


class ProjParams(BaseModel):
    project_key: str


async def query_d365_project_handler(params: ProjParams) -> str:
    result = await _facade().lookup_project(params.project_key)
    return _log_d365_tool_result("query_d365_project", params, result)


def build_functions() -> list[Function[Any]]:
    return [
        Function[CreateTaskToolParams](
            name="create_task",
            description=(
                "Propose a task (does not persist until user confirms the Adaptive Card). "
                "Call immediately when task_type, description, assignee_entra_id, assignee_department_code, "
                "due_date, and priority are known — the Confirm card is the only confirmation step. "
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
        Function[POParams](
            name="query_d365_po",
            description="Read-only PO lookup (named façade).",
            parameter_schema=POParams,
            handler=query_d365_po_handler,
        ),
        Function[VendorParams](
            name="query_d365_vendor",
            description="Read-only vendor lookup.",
            parameter_schema=VendorParams,
            handler=query_d365_vendor_handler,
        ),
        Function[CustomerParams](
            name="query_d365_customer",
            description="Read-only customer lookup.",
            parameter_schema=CustomerParams,
            handler=query_d365_customer_handler,
        ),
        Function[APInvParams](
            name="query_d365_invoice_ap",
            description="AP invoice lookup.",
            parameter_schema=APInvParams,
            handler=query_d365_invoice_ap_handler,
        ),
        Function[ARInvParams](
            name="query_d365_invoice_ar",
            description="AR invoice lookup by invoice number or customer account (e.g. C0002).",
            parameter_schema=ARInvParams,
            handler=query_d365_invoice_ar_handler,
        ),
        Function[EmpParams](
            name="query_d365_employee",
            description="Optional worker enrichment lookup — not authoritative identity.",
            parameter_schema=EmpParams,
            handler=query_d365_employee_handler,
        ),
        Function[ProjParams](
            name="query_d365_project",
            description="Project id or name keyed lookup.",
            parameter_schema=ProjParams,
            handler=query_d365_project_handler,
        ),
    ]


_GROQ_CHAT_TOOL_NAMES = frozenset(
    {"create_task", "list_tasks", "close_task", "reopen_task", "resume_task", "get_task_status"}
)


def build_functions_for_groq_chat() -> list[Function[Any]]:
    """Legacy 4-tool subset; prefer LLM_TOOL_PROFILE=full for D365 lookups."""
    return [f for f in build_functions() if f.name in _GROQ_CHAT_TOOL_NAMES]
