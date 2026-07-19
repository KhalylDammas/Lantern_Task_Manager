"""Load assignment profiles from assignment_directory.json."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ltm.config.artefacts import load_assignment_directory
from ltm.domain.enums import DEPT_DISPLAY, DeptCode
from ltm.policy.errors import ProfileNotFound


@dataclass(frozen=True)
class AssignmentProfile:
    entra_object_id: str
    department_code: DeptCode
    display_name: str = ""
    employee_code: str = ""
    manager_entra_id: str | None = None
    active: bool = True


def _parse_profile(entra_id: str, raw: dict[str, Any]) -> AssignmentProfile:
    dept_raw = str(raw.get("department_code") or "").strip().upper()
    try:
        dept = DeptCode(dept_raw)
    except ValueError as exc:
        raise ProfileNotFound(
            f"Directory entry for this user has invalid department_code '{dept_raw}'. Contact your administrator."
        ) from exc

    manager = raw.get("manager_entra_id")
    return AssignmentProfile(
        entra_object_id=entra_id,
        department_code=dept,
        display_name=str(raw.get("display_name") or ""),
        employee_code=str(raw.get("employee_code") or ""),
        manager_entra_id=str(manager) if manager else None,
        active=bool(raw.get("active", True)),
    )


@lru_cache
def _employees_index() -> dict[str, dict[str, Any]]:
    data = load_assignment_directory()
    employees = data.get("employees")
    if not isinstance(employees, dict):
        return {}
    return {str(k): v for k, v in employees.items() if isinstance(v, dict)}


def clear_profile_cache() -> None:
    _employees_index.cache_clear()


def get_profile(entra_object_id: str) -> AssignmentProfile:
    oid = (entra_object_id or "").strip()
    if not oid:
        raise ProfileNotFound("Missing user identity for assignment authorization.")

    raw = _employees_index().get(oid)
    if raw is None:
        raise ProfileNotFound(
            "You are not listed in the LTM assignment directory. Contact your administrator."
        )

    profile = _parse_profile(oid, raw)
    if not profile.active:
        raise ProfileNotFound(
            "Your LTM assignment directory entry is inactive. Contact your administrator."
        )
    return profile


def department_label(code: DeptCode) -> str:
    return DEPT_DISPLAY.get(code, code.value)
