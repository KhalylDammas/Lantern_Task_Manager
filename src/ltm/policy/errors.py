"""Assignment policy errors surfaced to users and tools."""

from __future__ import annotations

import json


def tool_error(code: str, message: str) -> str:
    """Serialize a structured tool failure the model can relay verbatim.

    Stable codes (NOT_ASSIGNEE, NOT_VERIFIER, INVALID_STATUS, NOT_FOUND,
    POLICY_DENIED) let the agent give consistent answers without inventing policy.
    """
    return json.dumps({"ok": False, "code": code, "message": message})


class AssignmentPolicyError(Exception):
    """Base for assignment authorization failures."""

    def __init__(self, user_message: str) -> None:
        self.user_message = user_message
        super().__init__(user_message)


class ProfileNotFound(AssignmentPolicyError):
    """Entra id missing from assignment_directory.json or inactive."""


class PolicyDenied(AssignmentPolicyError):
    """Requester may not assign to assignee under current policy."""
