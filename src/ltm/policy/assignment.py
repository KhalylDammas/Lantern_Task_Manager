"""Evaluate requester → assignee assignment rules."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ltm.config.artefacts import load_assignment_policy
from ltm.domain.enums import DeptCode
from ltm.policy.errors import PolicyDenied, ProfileNotFound
from ltm.policy.profiles import AssignmentProfile, department_label, get_profile


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    message: str = ""


def _matches(side: dict[str, Any], profile: AssignmentProfile) -> bool:
    if not side:
        return False
    if "entra_object_id" in side and str(side["entra_object_id"]) != profile.entra_object_id:
        return False
    if "department_code" in side:
        expected = str(side["department_code"]).strip().upper()
        if expected != profile.department_code.value:
            return False
    return True


def _edge_applies(edge: dict[str, Any], requester: AssignmentProfile, assignee: AssignmentProfile) -> bool:
    from_side = edge.get("from") if isinstance(edge.get("from"), dict) else {}
    to_side = edge.get("to") if isinstance(edge.get("to"), dict) else {}
    if _matches(from_side, requester) and _matches(to_side, assignee):
        return True
    if edge.get("bidirectional"):
        if _matches(from_side, assignee) and _matches(to_side, requester):
            return True
    return False


@lru_cache
def _policy_config() -> dict[str, Any]:
    return load_assignment_policy()


def clear_policy_cache() -> None:
    _policy_config.cache_clear()


def _ceo_department_codes(policy: dict[str, Any]) -> set[str]:
    raw = policy.get("ceo_department_codes")
    if isinstance(raw, list) and raw:
        return {str(code).strip().upper() for code in raw}
    return {DeptCode.CEO.value}


def _ceo_may_assign_direct_report(
    policy: dict[str, Any], requester: AssignmentProfile, assignee: AssignmentProfile
) -> bool:
    if not policy.get("allow_ceo_to_direct_reports", True):
        return False
    if requester.department_code.value not in _ceo_department_codes(policy):
        return False
    return bool(assignee.manager_entra_id) and assignee.manager_entra_id == requester.entra_object_id


def can_assign(requester: AssignmentProfile, assignee: AssignmentProfile) -> PolicyResult:
    policy = _policy_config()
    defaults = policy.get("defaults") if isinstance(policy.get("defaults"), dict) else {}

    deny_edges = policy.get("deny_edges") if isinstance(policy.get("deny_edges"), list) else []
    for edge in deny_edges:
        if isinstance(edge, dict) and _edge_applies(edge, requester, assignee):
            return PolicyResult(
                allowed=False,
                message=(
                    f"Assignment from {department_label(requester.department_code)} to "
                    f"{department_label(assignee.department_code)} is not allowed under current policy."
                ),
            )

    if _ceo_may_assign_direct_report(policy, requester, assignee):
        return PolicyResult(allowed=True)

    if requester.department_code == assignee.department_code and defaults.get("allow_same_department", True):
        return PolicyResult(allowed=True)

    edges = policy.get("edges") if isinstance(policy.get("edges"), list) else []
    for edge in edges:
        if isinstance(edge, dict) and _edge_applies(edge, requester, assignee):
            return PolicyResult(allowed=True)

    if (
        requester.department_code != assignee.department_code
        and defaults.get("allow_cross_department", False)
    ):
        return PolicyResult(allowed=True)

    return PolicyResult(
        allowed=False,
        message=(
            f"Assignment from {department_label(requester.department_code)} to "
            f"{department_label(assignee.department_code)} is not allowed under current policy."
        ),
    )


def assert_assignee_department_matches(
    *,
    assignee_entra_id: str,
    assignee_department_code: DeptCode,
) -> AssignmentProfile:
    """Directory is authoritative; tool/card dept must match."""
    try:
        profile = get_profile(assignee_entra_id)
    except ProfileNotFound as exc:
        raise ProfileNotFound(
            "The assignee is not listed in the LTM assignment directory. "
            "Ask an administrator to add the assignee before creating this task."
        ) from exc
    if profile.department_code != assignee_department_code:
        raise PolicyDenied(
            "Assignee department does not match the LTM assignment directory. "
            f"Directory has {profile.department_code.value}; request had {assignee_department_code.value}."
        )
    return profile


def assert_can_assign(*, requester_entra_id: str, assignee_entra_id: str) -> None:
    """Raise ProfileNotFound or PolicyDenied when assignment is not permitted."""
    try:
        requester = get_profile(requester_entra_id)
    except ProfileNotFound as exc:
        raise ProfileNotFound(
            "Your account is not listed in the LTM assignment directory. "
            "Ask an administrator to add your account before creating tasks."
        ) from exc
    try:
        assignee = get_profile(assignee_entra_id)
    except ProfileNotFound as exc:
        raise ProfileNotFound(
            "The assignee is not listed in the LTM assignment directory. "
            "Ask an administrator to add the assignee before creating this task."
        ) from exc
    result = can_assign(requester, assignee)
    if not result.allowed:
        raise PolicyDenied(result.message)
