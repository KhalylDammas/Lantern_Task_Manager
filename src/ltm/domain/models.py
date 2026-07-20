"""Pydantic models for tasks (DM-01)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field

from ltm.domain.enums import AuditEvent, DeptCode, Priority, TaskStatus


class UserRef(BaseModel):
    entra_object_id: str
    display_name: str = ""
    department: str = ""


class D365References(BaseModel):
    purchase_order_number: str | None = None
    vendor_account: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    customer_account: str | None = None
    project_id: str | None = None


class AuditEntry(BaseModel):
    event: AuditEvent | str
    actor_entra_id: str
    at: datetime | str
    details: str = ""


class TaskRecord(BaseModel):
    id: str
    task_type: str
    department: str
    description: str
    status: TaskStatus
    priority: Priority | str
    created_by: UserRef
    assigned_to: UserRef
    due_date: date
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    verified_at: datetime | None = None
    closure_notes: str = ""
    rejection_reason: str = ""
    is_overdue: bool = False
    escalation_count: int = 0
    last_escalated_at: datetime | None = None
    d365_references: D365References = Field(default_factory=D365References)
    audit_trail: list[AuditEntry] = Field(default_factory=list)


class TaskCreateDraft(BaseModel):
    task_type: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(min_length=1, max_length=8000)]
    assignee_entra_id: Annotated[str, Field(min_length=1)]
    assignee_display_name: str = ""
    assignee_department: str = ""
    assignee_department_code: Annotated[DeptCode, Field(description="Assignee home department code")]
    priority: Priority | str = Priority.MEDIUM
    due_date: date
    d365: D365References = Field(default_factory=D365References)


class CloseTaskParams(BaseModel):
    task_id: str
    completion_notes: Annotated[str, Field(min_length=1, max_length=8000)]


class AcknowledgeTaskParams(BaseModel):
    task_id: str


class DraftActionParams(BaseModel):
    draft_id: str


class VerifyTaskParams(BaseModel):
    task_id: str


class ReopenTaskParams(BaseModel):
    task_id: str
    reason: Annotated[str, Field(min_length=1, max_length=8000)]


class ResumeTaskParams(BaseModel):
    task_id: str


class ListTasksParams(BaseModel):
    filter: Literal[
        "my_tasks",
        "my_requests",
        "department",
        "all_overdue",
        "pending_verification",
        "my_overdue",
        "my_pending_verification",
    ] = "my_tasks"
    department: str | None = None
    status: TaskStatus | None = None
    limit: int = Field(default=25, ge=1, le=100)


class GetTaskParams(BaseModel):
    task_id: str | None = None
    query: str | None = None


class ManagerVerifySubmit(BaseModel):
    verb: Literal["manager_verify_confirm", "manager_verify_reject"]
    task_id: str
    rejection_reason: str = ""
