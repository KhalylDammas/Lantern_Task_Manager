"""Assignment authorization (Unit #1)."""

from ltm.policy.assignment import assert_can_assign, assert_assignee_department_matches
from ltm.policy.errors import AssignmentPolicyError, PolicyDenied, ProfileNotFound, tool_error

__all__ = [
    "AssignmentPolicyError",
    "PolicyDenied",
    "ProfileNotFound",
    "assert_can_assign",
    "assert_assignee_department_matches",
    "tool_error",
]
