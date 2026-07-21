#!/usr/bin/env python3
"""Build assignment_directory.json from assignment_directory.csv (+ optional Graph enrich).

Usage (from repo root):
  python scripts/seed_assignment_directory.py build
  python scripts/seed_assignment_directory.py export-candidates
  python scripts/seed_assignment_directory.py enrich --include  # refresh Graph fields for included rows

Requires `az login` for export-candidates and enrich.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "src" / "config"
CSV_PATH = CONFIG_DIR / "assignment_directory.csv"
JSON_PATH = CONFIG_DIR / "assignment_directory.json"
CANDIDATES_PATH = CONFIG_DIR / "assignment_directory.candidates.csv"

VALID_DEPT = frozenset({"FIN", "PROC", "OP", "HR", "IT", "CEO"})

DEPT_FROM_GRAPH = {
    "finance": "FIN",
    "procurement": "FIN",
    "proc": "PROC",
    "operation": "OP",
    "operations": "OP",
    "op": "OP",
    "hr": "HR",
    "human resources": "HR",
    "it": "IT",
    "it & systems": "IT",
}


def _department_code(raw: str) -> str:
    normalized = (raw or "").strip().lower()
    if not normalized:
        return ""
    if normalized.upper() in VALID_DEPT:
        return normalized.upper()
    return DEPT_FROM_GRAPH.get(normalized, "")


def _graph_get(path: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["az", "rest", "--method", "GET", "--uri", path, "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "az rest failed")
    return json.loads(proc.stdout)


def enrich_user(entra_id: str) -> dict[str, str]:
    path = (
        "https://graph.microsoft.com/v1.0/users/"
        f"{entra_id}?$select=displayName,mail,jobTitle,department"
        "&$expand=manager($select=id,displayName)"
    )
    data = _graph_get(path)
    manager = data.get("manager") if isinstance(data.get("manager"), dict) else {}
    dept = _department_code(str(data.get("department") or ""))
    return {
        "display_name": str(data.get("displayName") or ""),
        "mail": str(data.get("mail") or ""),
        "job_title": str(data.get("jobTitle") or ""),
        "graph_department": str(data.get("department") or ""),
        "department_code": dept,
        "manager_entra_id": str(manager.get("id") or ""),
        "manager_display_name": str(manager.get("displayName") or ""),
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_json_from_csv(rows: list[dict[str, str]]) -> dict[str, Any]:
    employees: dict[str, dict[str, Any]] = {}
    for row in rows:
        if (row.get("include") or "").strip().upper() not in {"Y", "YES", "TRUE", "1"}:
            continue
        entra_id = (row.get("entra_object_id") or "").strip()
        dept = (row.get("department_code") or "").strip().upper()
        if not entra_id:
            raise ValueError(f"Row missing entra_object_id: {row}")
        if dept not in VALID_DEPT:
            raise ValueError(
                f"{row.get('display_name') or entra_id}: department_code must be one of {sorted(VALID_DEPT)}"
            )
        entry: dict[str, Any] = {
            "display_name": (row.get("display_name") or "").strip(),
            "department_code": dept,
            "active": (row.get("active") or "Y").strip().upper() not in {"N", "NO", "FALSE", "0"},
        }
        if row.get("employee_code", "").strip():
            entry["employee_code"] = row["employee_code"].strip()
        mgr = (row.get("manager_entra_id") or "").strip()
        if mgr:
            entry["manager_entra_id"] = mgr
        employees[entra_id] = entry

    return {
        "version": 1,
        "notes": "Generated from assignment_directory.csv. Edit CSV then run: python scripts/seed_assignment_directory.py build",
        "employees": employees,
    }


def cmd_build(_: argparse.Namespace) -> None:
    rows = read_csv(CSV_PATH)
    payload = build_json_from_csv(rows)
    JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['employees'])} employees to {JSON_PATH}")


def cmd_enrich(args: argparse.Namespace) -> None:
    rows = read_csv(CSV_PATH)
    fieldnames = list(rows[0].keys()) if rows else []
    for extra in (
        "graph_department",
        "job_title",
        "mail",
        "manager_display_name",
    ):
        if extra not in fieldnames:
            fieldnames.append(extra)

    updated = 0
    for row in rows:
        if args.include_only and (row.get("include") or "").strip().upper() not in {"Y", "YES", "TRUE", "1"}:
            continue
        entra_id = (row.get("entra_object_id") or "").strip()
        if not entra_id:
            continue
        try:
            info = enrich_user(entra_id)
        except Exception as exc:  # noqa: BLE001
            print(f"skip {entra_id}: {exc}", file=sys.stderr)
            continue
        row["display_name"] = row.get("display_name") or info["display_name"]
        row["mail"] = info["mail"]
        row["job_title"] = info["job_title"]
        row["graph_department"] = info["graph_department"]
        if not (row.get("department_code") or "").strip() and info["department_code"]:
            row["department_code"] = info["department_code"]
        if not (row.get("manager_entra_id") or "").strip() and info["manager_entra_id"]:
            row["manager_entra_id"] = info["manager_entra_id"]
        row["manager_display_name"] = info["manager_display_name"]
        updated += 1

    write_csv(CSV_PATH, rows, fieldnames)
    print(f"Enriched {updated} rows in {CSV_PATH}")


def _is_service_account(display_name: str, upn: str) -> bool:
    dn = display_name.strip()
    if not dn or len(dn) < 4:
        return True
    if "#EXT#" in upn:
        return True
    if not re.search(r"\s", dn) and dn.lower() not in {"ceo"}:
        return True
    skip = re.compile(
        r"^(VMware|Automation|Power BI|Book Meeting|Document Control|HR Helpdesk|System Notification|Storageadmin|Subscriptions|Training|TASKDUE|TACHYON|VECTOR|QUANTUM|PHOTON|Bizdev|lant|prox|voip|xerox|replication|acc_test)",
        re.I,
    )
    return bool(skip.search(dn) or skip.search(upn.split("@")[0]))


def cmd_export_candidates(_: argparse.Namespace) -> None:
    proc = subprocess.run(["az", "ad", "user", "list", "-o", "json"], capture_output=True, text=True, check=True)
    users = json.loads(proc.stdout)
    fieldnames = [
        "include",
        "entra_object_id",
        "display_name",
        "mail",
        "job_title",
        "graph_department",
        "department_code",
        "employee_code",
        "manager_entra_id",
        "manager_display_name",
        "active",
        "notes",
    ]
    rows: list[dict[str, str]] = []
    for u in sorted(users, key=lambda x: (x.get("displayName") or "").lower()):
        upn = u.get("userPrincipalName") or ""
        if not upn.endswith("@lanternsystems.com"):
            continue
        dn = u.get("displayName") or ""
        if _is_service_account(dn, upn):
            continue
        if not (u.get("mail") or u.get("givenName")):
            continue
        rows.append(
            {
                "include": "",
                "entra_object_id": u["id"],
                "display_name": dn,
                "mail": u.get("mail") or "",
                "job_title": u.get("jobTitle") or "",
                "graph_department": "",
                "department_code": "",
                "employee_code": "",
                "manager_entra_id": "",
                "manager_display_name": "",
                "active": "Y",
                "notes": "",
            }
        )
    write_csv(CANDIDATES_PATH, rows, fieldnames)
    print(f"Wrote {len(rows)} candidate rows to {CANDIDATES_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Write assignment_directory.json from CSV").set_defaults(func=cmd_build)
    p_enrich = sub.add_parser("enrich", help="Fill Graph fields on CSV rows")
    p_enrich.add_argument("--include", action="store_true", dest="include_only", help="Only rows with include=Y")
    p_enrich.set_defaults(func=cmd_enrich)
    sub.add_parser("export-candidates", help="Export Entra users to candidates CSV").set_defaults(
        func=cmd_export_candidates
    )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
