"""State transitions for tasks (FR-WF-01)."""

from __future__ import annotations

from ltm.domain.enums import TaskStatus

_DISALLOWED_CANCEL: set[TaskStatus] = {
    TaskStatus.CANCELLED,
    TaskStatus.VERIFIED,
}


def can_transition(from_status: TaskStatus, to_status: TaskStatus, *, request_cancel: bool = False) -> bool:
    """Return whether a transition is allowed (simplified guard)."""
    if request_cancel:
        return from_status not in _DISALLOWED_CANCEL and to_status == TaskStatus.CANCELLED

    if from_status == to_status:
        return True

    transitions: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.CREATED: {TaskStatus.ASSIGNED, TaskStatus.CANCELLED},
        TaskStatus.ASSIGNED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
        TaskStatus.IN_PROGRESS: {
            TaskStatus.PENDING_CLOSURE,
            TaskStatus.PENDING_VERIFICATION,
            TaskStatus.CANCELLED,
        },
        TaskStatus.PENDING_CLOSURE: {TaskStatus.PENDING_VERIFICATION, TaskStatus.IN_PROGRESS},
        TaskStatus.PENDING_VERIFICATION: {
            TaskStatus.VERIFIED,
            TaskStatus.REOPENED,
        },
        TaskStatus.REOPENED: {
            TaskStatus.IN_PROGRESS,
            TaskStatus.PENDING_VERIFICATION,
            TaskStatus.CANCELLED,
        },
        TaskStatus.VERIFIED: set(),
        TaskStatus.CANCELLED: set(),
    }
    return to_status in transitions.get(from_status, set())
