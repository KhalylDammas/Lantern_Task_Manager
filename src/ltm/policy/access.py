"""Task read-access policy shared by chat tools and card actions."""

from __future__ import annotations

from ltm.config.settings import Settings
from ltm.domain.enums import DeptCode
from ltm.domain.models import TaskRecord
from ltm.notifications.recipients import is_verifier
from ltm.policy.errors import AssignmentPolicyError
from ltm.policy.profiles import get_profile


def is_executive(user_entra_id: str) -> bool:
    """Return whether an active assignment-directory profile is a CEO profile."""
    try:
        return get_profile(user_entra_id).department_code == DeptCode.CEO
    except AssignmentPolicyError:
        return False


def can_view_task(user_entra_id: str, task: TaskRecord, settings: Settings) -> bool:
    """Restrict task details to participants, the verifier, and executive oversight."""
    oid = (user_entra_id or "").strip()
    if not oid:
        return False
    if oid in {task.created_by.entra_object_id, task.assigned_to.entra_object_id}:
        return True
    return is_executive(oid) or is_verifier(oid, task, settings)
