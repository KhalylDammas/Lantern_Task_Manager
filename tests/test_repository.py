from datetime import date, timedelta

from ltm.domain.enums import DeptCode, Priority, TaskStatus
from ltm.domain.models import CloseTaskParams, TaskCreateDraft, UserRef
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository


def test_create_assignee_close_cycle():
    requester = UserRef(entra_object_id="req-1", display_name="Requester", department="PROC")
    assignee = UserRef(entra_object_id="asg-1", display_name="Ahmed", department="Finance")
    draft = TaskCreateDraft(
        task_type="LC Opening",
        description="Open LC for demo",
        assignee_entra_id=assignee.entra_object_id,
        assignee_display_name=assignee.display_name,
        assignee_department=assignee.department,
        assignee_department_code=DeptCode.FIN,
        priority=Priority.HIGH,
        due_date=date.today() + timedelta(days=7),
    )
    with session_scope() as s:
        repo = TaskRepository(s)
        rec = repo.create_from_draft(draft, requester)
        assert rec.id.startswith("LTM-FIN-")
        rec = repo.assignee_acknowledge(rec.id, assignee.entra_object_id)
        assert TaskStatus(rec.status) == TaskStatus.IN_PROGRESS
        rec2 = repo.mark_pending_closure_from_assignee(CloseTaskParams(task_id=rec.id, completion_notes="Done"), assignee.entra_object_id)
        assert TaskStatus(rec2.status) == TaskStatus.PENDING_VERIFICATION
