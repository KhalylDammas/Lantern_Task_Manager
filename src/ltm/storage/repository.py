"""Task persistence (DM-01, FR-WF-02)."""

from __future__ import annotations

import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ltm.domain.business_time import business_now, business_today
from ltm.domain.enums import AuditEvent, DeptCode, DEPT_DISPLAY, TaskStatus
from ltm.domain.models import AuditEntry, CloseTaskParams, D365References, ListTasksParams, TaskRecord, TaskCreateDraft, UserRef
from ltm.domain.state_machine import can_transition
from ltm.storage.orm import TaskCounter, TaskORM

logger = logging.getLogger(__name__)


def _now():
    return business_now()


def _public_id(dept: DeptCode, year: int, seq: int) -> str:
    return f"LTM-{dept.value}-{year}-{seq:04d}"


def _orm_to_record(row: TaskORM) -> TaskRecord:
    audits = [AuditEntry(**a) for a in (row.audit_trail or [])]
    return TaskRecord(
        id=row.task_id,
        task_type=row.task_type,
        department=row.department_display,
        description=row.description,
        status=TaskStatus(row.status),
        priority=row.priority,
        created_by=UserRef(
            entra_object_id=row.created_by_entra_id,
            display_name=row.created_by_display_name,
            department=row.created_by_department,
        ),
        assigned_to=UserRef(
            entra_object_id=row.assigned_to_entra_id,
            display_name=row.assigned_to_display_name,
            department=row.assigned_to_department,
        ),
        due_date=row.due_date,
        created_at=row.created_at,
        updated_at=row.updated_at,
        closed_at=row.closed_at,
        verified_at=row.verified_at,
        closure_notes=row.closure_notes,
        rejection_reason=row.rejection_reason,
        is_overdue=row.is_overdue,
        escalation_count=row.escalation_count,
        last_escalated_at=row.last_escalated_at,
        d365_references=D365References.model_validate(row.d365_references or {}),
        audit_trail=audits,
    )


class TaskRepository:
    def __init__(self, session: Session):
        self.s = session

    def _transition(
        self,
        row: TaskORM,
        *,
        target: TaskStatus,
        actor_entra_id: str,
        audit_event: str,
        details: str = "",
    ) -> None:
        """Apply a guarded status change with an audit entry (shared by lifecycle steps)."""
        current = TaskStatus(row.status)
        if not can_transition(current, target):
            raise ValueError(f"Cannot move task from {current.value} to {target.value}")
        now = _now()
        row.status = target.value
        row.updated_at = now
        audits = list(row.audit_trail or [])
        audits.append(
            {
                "event": audit_event,
                "actor_entra_id": actor_entra_id,
                "at": now.isoformat(),
                "details": details[:1000],
            }
        )
        row.audit_trail = audits

    def next_sequence(self, dept: DeptCode, year: int | None = None) -> int:
        y = year or business_today().year
        row = self.s.execute(
            select(TaskCounter).where(TaskCounter.department_code == dept.value, TaskCounter.year == y)
        ).scalar_one_or_none()
        if row is None:
            row = TaskCounter(department_code=dept.value, year=y, last_sequence=0)
            self.s.add(row)
            self.s.flush()

        row.last_sequence += 1
        self.s.flush()
        return row.last_sequence

    def create_from_draft(self, draft: TaskCreateDraft, requester: UserRef) -> TaskRecord:
        year = business_today().year
        seq = self.next_sequence(draft.assignee_department_code, year)
        task_id = _public_id(draft.assignee_department_code, year, seq)
        now = _now()

        assignee = UserRef(
            entra_object_id=draft.assignee_entra_id,
            display_name=draft.assignee_display_name,
            department=draft.assignee_department,
        )

        audit = [
            {
                "event": AuditEvent.CREATED.value,
                "actor_entra_id": requester.entra_object_id,
                "at": now.isoformat(),
                "details": "",
            },
            {
                "event": AuditEvent.ASSIGNED.value,
                "actor_entra_id": requester.entra_object_id,
                "at": now.isoformat(),
                "details": assignee.entra_object_id,
            },
        ]

        row = TaskORM(
            task_id=task_id,
            task_type=draft.task_type,
            department_display=DEPT_DISPLAY[draft.assignee_department_code],
            department_code=draft.assignee_department_code.value,
            description=draft.description,
            status=TaskStatus.ASSIGNED.value,
            priority=str(draft.priority.value if hasattr(draft.priority, "value") else draft.priority),
            created_by_entra_id=requester.entra_object_id,
            created_by_display_name=requester.display_name,
            created_by_department=requester.department,
            assigned_to_entra_id=assignee.entra_object_id,
            assigned_to_display_name=assignee.display_name,
            assigned_to_department=assignee.department,
            due_date=draft.due_date,
            created_at=now,
            updated_at=now,
            d365_references=draft.d365.model_dump(),
            audit_trail=audit,
        )
        self.s.add(row)
        self.s.flush()
        return _orm_to_record(row)

    def get(self, task_id: str) -> TaskRecord | None:
        row = self.s.get(TaskORM, task_id)
        return _orm_to_record(row) if row else None

    def search(self, query: str, limit: int = 10) -> Sequence[TaskRecord]:
        like = f"%{query.lower()}%"
        rows = self.s.execute(
            select(TaskORM)
            .where(
                (TaskORM.task_id.ilike(like))
                | (TaskORM.description.ilike(like))
                | (TaskORM.task_type.ilike(like))
            )
            .limit(limit)
        ).scalars()
        return [_orm_to_record(r) for r in rows]

    def list_tasks(
        self,
        params: ListTasksParams,
        viewer_entra_id: str,
        *,
        apply_limit: bool = True,
    ) -> Sequence[TaskRecord]:
        stmt = select(TaskORM)
        status_val = params.status.value if params.status else None

        if params.filter == "my_tasks":
            stmt = stmt.where(TaskORM.assigned_to_entra_id == viewer_entra_id)
        elif params.filter == "my_requests":
            stmt = stmt.where(TaskORM.created_by_entra_id == viewer_entra_id)
        elif params.filter == "department" and params.department:
            stmt = stmt.where(TaskORM.department_display == params.department)
        elif params.filter == "all_overdue":
            stmt = stmt.where(TaskORM.is_overdue.is_(True))
        elif params.filter == "pending_verification":
            stmt = stmt.where(TaskORM.status == TaskStatus.PENDING_VERIFICATION.value)
        elif params.filter == "my_overdue":
            stmt = stmt.where(
                TaskORM.assigned_to_entra_id == viewer_entra_id,
                TaskORM.is_overdue.is_(True),
            )
        elif params.filter == "my_pending_verification":
            stmt = stmt.where(
                TaskORM.created_by_entra_id == viewer_entra_id,
                TaskORM.status == TaskStatus.PENDING_VERIFICATION.value,
            )

        if status_val:
            stmt = stmt.where(TaskORM.status == status_val)

        stmt = stmt.order_by(TaskORM.due_date)
        if apply_limit:
            stmt = stmt.limit(params.limit)
        rows = self.s.execute(stmt).scalars()
        return [_orm_to_record(r) for r in rows]

    def assignee_acknowledge(self, task_id: str, assignee_entra_id: str) -> TaskRecord:
        """Assignee accepts a newly assigned task: ASSIGNED -> IN_PROGRESS."""
        row = self.s.get(TaskORM, task_id)
        if not row:
            raise ValueError("Task not found")
        if row.assigned_to_entra_id != assignee_entra_id:
            raise ValueError("Only the assignee can acknowledge this task")
        if row.status != TaskStatus.ASSIGNED.value:
            raise ValueError("Task is not awaiting acknowledgement")
        self._transition(
            row,
            target=TaskStatus.IN_PROGRESS,
            actor_entra_id=assignee_entra_id,
            audit_event=AuditEvent.ACKNOWLEDGED.value,
        )
        self.s.flush()
        return _orm_to_record(row)

    def assignee_resume(self, task_id: str, assignee_entra_id: str) -> TaskRecord:
        """Assignee resumes work after a reopen: REOPENED -> IN_PROGRESS."""
        row = self.s.get(TaskORM, task_id)
        if not row:
            raise ValueError("Task not found")
        if row.assigned_to_entra_id != assignee_entra_id:
            raise ValueError("Only the assignee can resume this task")
        if row.status != TaskStatus.REOPENED.value:
            raise ValueError("Task is not reopened")
        self._transition(
            row,
            target=TaskStatus.IN_PROGRESS,
            actor_entra_id=assignee_entra_id,
            audit_event=AuditEvent.RESUMED.value,
        )
        self.s.flush()
        return _orm_to_record(row)

    def mark_pending_closure_from_assignee(self, params: CloseTaskParams, assignee_entra_id: str) -> TaskRecord:
        """Request verification, recovering gracefully when acknowledgement was missed.

        Completing work is also an unambiguous acknowledgement of the assignment.  Keeping
        the intermediate transition makes the recovery visible in the audit trail instead of
        weakening the state machine with an ASSIGNED -> PENDING_VERIFICATION shortcut.
        """
        row = self.s.get(TaskORM, params.task_id)
        if not row:
            raise ValueError("Task not found")
        if row.assigned_to_entra_id != assignee_entra_id:
            raise ValueError("Only the assignee can close this task")

        if row.status == TaskStatus.ASSIGNED.value:
            self._transition(
                row,
                target=TaskStatus.IN_PROGRESS,
                actor_entra_id=assignee_entra_id,
                audit_event=AuditEvent.ACKNOWLEDGED.value,
                details="Implicit acknowledgement on close",
            )

        row.closure_notes = params.completion_notes
        self._transition(
            row,
            target=TaskStatus.PENDING_VERIFICATION,
            actor_entra_id=assignee_entra_id,
            audit_event=AuditEvent.CLOSURE_REQUESTED.value,
            details=params.completion_notes,
        )
        self.s.flush()
        return _orm_to_record(row)

    def manager_confirm(self, task_id: str, manager_entra_id: str) -> TaskRecord:
        row = self.s.get(TaskORM, task_id)
        if not row:
            raise ValueError("Task not found")
        if row.status != TaskStatus.PENDING_VERIFICATION.value:
            raise ValueError("Task is not pending verification")

        row.status = TaskStatus.VERIFIED.value
        row.verified_at = _now()
        row.updated_at = row.verified_at
        audits = list(row.audit_trail or [])
        audits.append(
            {
                "event": AuditEvent.VERIFIED.value,
                "actor_entra_id": manager_entra_id,
                "at": row.updated_at.isoformat(),
                "details": "",
            }
        )
        row.audit_trail = audits
        self.s.flush()
        return _orm_to_record(row)

    def manager_reject(self, task_id: str, manager_entra_id: str, reason: str) -> TaskRecord:
        row = self.s.get(TaskORM, task_id)
        if not row:
            raise ValueError("Task not found")
        if row.status != TaskStatus.PENDING_VERIFICATION.value:
            raise ValueError("Task is not pending verification")

        row.status = TaskStatus.REOPENED.value
        row.rejection_reason = reason
        row.updated_at = _now()
        audits = list(row.audit_trail or [])
        audits.append(
            {
                "event": AuditEvent.REOPENED.value,
                "actor_entra_id": manager_entra_id,
                "at": row.updated_at.isoformat(),
                "details": reason[:1000],
            }
        )
        row.audit_trail = audits
        self.s.flush()
        return _orm_to_record(row)

    def list_overdue_in_progress(self) -> Sequence[TaskRecord]:
        today = business_today()
        rows = self.s.execute(
            select(TaskORM).where(
                TaskORM.status == TaskStatus.IN_PROGRESS.value,
                TaskORM.due_date < today,
            )
        ).scalars()
        return [_orm_to_record(r) for r in rows]

    def list_open_for_assignee(self, assignee_entra_id: str) -> Sequence[TaskRecord]:
        open_statuses = {
            TaskStatus.CREATED.value,
            TaskStatus.ASSIGNED.value,
            TaskStatus.IN_PROGRESS.value,
            TaskStatus.PENDING_CLOSURE.value,
            TaskStatus.PENDING_VERIFICATION.value,
            TaskStatus.REOPENED.value,
        }
        rows = self.s.execute(
            select(TaskORM)
            .where(
                TaskORM.assigned_to_entra_id == assignee_entra_id,
                TaskORM.status.in_(open_statuses),
            )
            .order_by(TaskORM.due_date)
        ).scalars()
        return [_orm_to_record(r) for r in rows]

    def refresh_overdue_flags(self) -> int:
        today = business_today()
        terminal = {TaskStatus.VERIFIED.value, TaskStatus.CANCELLED.value}
        n = 0
        rows = self.s.execute(select(TaskORM)).scalars().all()
        for row in rows:
            overdue = row.due_date < today and row.status not in terminal
            if row.is_overdue != overdue:
                row.is_overdue = overdue
                row.updated_at = _now()
                n += 1
        self.s.flush()
        return n

    def distinct_assignees_with_open_tasks(self) -> list[str]:
        terminal = {
            TaskStatus.VERIFIED.value,
            TaskStatus.CANCELLED.value,
        }
        rows = (
            self.s.execute(select(TaskORM.assigned_to_entra_id).where(TaskORM.status.not_in(terminal)).distinct())
            .scalars()
            .all()
        )
        return list(rows)

    def append_audit(
        self,
        task_id: str,
        *,
        event: str,
        actor_entra_id: str,
        details: str = "",
    ) -> None:
        row = self.s.get(TaskORM, task_id)
        if row is None:
            return
        audits = list(row.audit_trail or [])
        audits.append(
            {
                "event": event,
                "actor_entra_id": actor_entra_id,
                "at": _now().isoformat(),
                "details": details[:1000],
            }
        )
        row.audit_trail = audits
        row.updated_at = _now()
        self.s.flush()
