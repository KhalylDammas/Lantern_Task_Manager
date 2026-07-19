"""Assignment authorization (Unit #1)."""

from __future__ import annotations

import pytest

from ltm.domain.enums import DeptCode
from ltm.policy.assignment import (
    assert_assignee_department_matches,
    assert_can_assign,
    can_assign,
    clear_policy_cache,
)
from ltm.policy.errors import PolicyDenied, ProfileNotFound
from ltm.policy.profiles import AssignmentProfile, clear_profile_cache, get_profile


@pytest.fixture
def policy_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    directory = {
        "version": 1,
        "employees": {
            "req-fin": {
                "display_name": "Requester FIN",
                "department_code": "FIN",
                "active": True,
            },
            "asg-fin": {"department_code": "FIN", "active": True},
            "asg-it": {"department_code": "IT", "active": True},
            "req-proc": {"department_code": "PROC", "active": True},
            "inactive": {"department_code": "HR", "active": False},
        },
    }
    policy = {
        "version": 1,
        "defaults": {"allow_same_department": True, "allow_cross_department": False},
        "edges": [
            {"from": {"department_code": "PROC"}, "to": {"department_code": "FIN"}, "bidirectional": False},
            {"from": {"department_code": "FIN"}, "to": {"department_code": "IT"}, "bidirectional": True},
        ],
        "deny_edges": [],
    }
    monkeypatch.setattr("ltm.policy.profiles.load_assignment_directory", lambda: directory)
    monkeypatch.setattr("ltm.policy.assignment.load_assignment_policy", lambda: policy)
    clear_profile_cache()
    clear_policy_cache()
    yield
    clear_profile_cache()
    clear_policy_cache()


def _profile(oid: str, dept: DeptCode) -> AssignmentProfile:
    return AssignmentProfile(entra_object_id=oid, department_code=dept)


def test_same_department_allowed(policy_configs: None) -> None:
    requester = get_profile("req-fin")
    assignee = get_profile("asg-fin")
    assert can_assign(requester, assignee).allowed
    assert_can_assign(requester_entra_id="req-fin", assignee_entra_id="asg-fin")


def test_cross_department_denied_without_edge(policy_configs: None) -> None:
    requester = get_profile("req-fin")
    assignee = _profile("x", DeptCode.HR)
    assert not can_assign(requester, assignee).allowed


def test_proc_to_fin_one_way(policy_configs: None) -> None:
    proc = get_profile("req-proc")
    fin = get_profile("asg-fin")
    assert can_assign(proc, fin).allowed
    assert not can_assign(fin, proc).allowed


def test_fin_it_bidirectional(policy_configs: None) -> None:
    fin = get_profile("req-fin")
    it = get_profile("asg-it")
    assert can_assign(fin, it).allowed
    assert can_assign(it, fin).allowed


def test_profile_not_found(policy_configs: None) -> None:
    with pytest.raises(ProfileNotFound):
        get_profile("unknown-entra-id")


def test_missing_requester_has_requester_message(policy_configs: None) -> None:
    with pytest.raises(ProfileNotFound, match="Your account is not listed"):
        assert_can_assign(requester_entra_id="unknown-requester", assignee_entra_id="asg-it")


def test_missing_assignee_has_assignee_message(policy_configs: None) -> None:
    with pytest.raises(ProfileNotFound, match="The assignee is not listed"):
        assert_can_assign(requester_entra_id="req-fin", assignee_entra_id="unknown-assignee")


def test_missing_assignee_department_check_has_assignee_message(policy_configs: None) -> None:
    with pytest.raises(ProfileNotFound, match="The assignee is not listed"):
        assert_assignee_department_matches(
            assignee_entra_id="unknown-assignee",
            assignee_department_code=DeptCode.IT,
        )


def test_inactive_profile_denied(policy_configs: None) -> None:
    with pytest.raises(ProfileNotFound):
        get_profile("inactive")


def test_department_spoof_denied(policy_configs: None) -> None:
    with pytest.raises(PolicyDenied):
        assert_assignee_department_matches(
            assignee_entra_id="asg-it",
            assignee_department_code=DeptCode.FIN,
        )


def test_department_match_passes(policy_configs: None) -> None:
    profile = assert_assignee_department_matches(
        assignee_entra_id="asg-it",
        assignee_department_code=DeptCode.IT,
    )
    assert profile.department_code == DeptCode.IT


def test_assert_can_assign_denies_fin_to_proc(policy_configs: None) -> None:
    with pytest.raises(PolicyDenied):
        assert_can_assign(requester_entra_id="req-fin", assignee_entra_id="req-proc")


def test_ceo_assigns_to_direct_report_only(monkeypatch: pytest.MonkeyPatch) -> None:
    directory = {
        "version": 1,
        "employees": {
            "ceo-1": {
                "display_name": "CEO",
                "department_code": "CEO",
                "active": True,
            },
            "report": {
                "display_name": "Direct Report",
                "department_code": "IT",
                "active": True,
                "manager_entra_id": "ceo-1",
            },
            "other": {
                "display_name": "Not a report",
                "department_code": "IT",
                "active": True,
                "manager_entra_id": "someone-else",
            },
        },
    }
    policy = {
        "version": 1,
        "allow_ceo_to_direct_reports": True,
        "ceo_department_codes": ["CEO"],
        "defaults": {"allow_same_department": True, "allow_cross_department": False},
        "edges": [],
        "deny_edges": [],
    }
    monkeypatch.setattr("ltm.policy.profiles.load_assignment_directory", lambda: directory)
    monkeypatch.setattr("ltm.policy.assignment.load_assignment_policy", lambda: policy)
    clear_profile_cache()
    clear_policy_cache()

    assert_can_assign(requester_entra_id="ceo-1", assignee_entra_id="report")
    with pytest.raises(PolicyDenied):
        assert_can_assign(requester_entra_id="ceo-1", assignee_entra_id="other")
    with pytest.raises(PolicyDenied):
        assert_can_assign(requester_entra_id="report", assignee_entra_id="ceo-1")


def test_ceo_direct_reports_with_live_config() -> None:
    """Jabir (CEO) and Khalyl from src/config assignment_directory + policy."""
    clear_profile_cache()
    clear_policy_cache()
    jabir = "d5b03abf-9013-49af-b7ee-890567cc792d"
    khalyl = "0e103a6b-8bf3-4afd-9236-64cca3052719"
    hafiz = "e5e8ca79-f97b-4487-b3a7-49068a62ee18"
    shaji = "cc99a627-c1a1-46dc-8518-3661981227b5"

    assert_can_assign(requester_entra_id=jabir, assignee_entra_id=khalyl)
    assert_can_assign(requester_entra_id=jabir, assignee_entra_id=hafiz)
    with pytest.raises(PolicyDenied):
        assert_can_assign(requester_entra_id=khalyl, assignee_entra_id=jabir)
    with pytest.raises(PolicyDenied):
        assert_can_assign(requester_entra_id=jabir, assignee_entra_id=shaji)
