from ltm.domain.enums import TaskStatus
from ltm.domain.state_machine import can_transition


def test_in_progress_to_pending_verification():
    assert can_transition(TaskStatus.IN_PROGRESS, TaskStatus.PENDING_VERIFICATION)


def test_verified_is_terminal():
    assert not can_transition(TaskStatus.VERIFIED, TaskStatus.IN_PROGRESS)
