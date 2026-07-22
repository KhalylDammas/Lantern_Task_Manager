"""Task enums (FR-WF-01…FR-WF-04)."""

from __future__ import annotations

from enum import StrEnum


class DeptCode(StrEnum):
    FIN = "FIN"
    PROC = "PROC"
    OP = "OP"
    HR = "HR"
    IT = "IT"
    BD = "BD"
    SAL = "SAL"
    EXO = "EXO"
    TBS = "TBS"
    CBS = "CBS"
    QUA = "QUA"
    CEO = "CEO"


DEPT_DISPLAY = {
    DeptCode.FIN: "Finance",
    DeptCode.PROC: "Procurement",
    DeptCode.OP: "Operation",
    DeptCode.HR: "HR",
    DeptCode.IT: "IT",
    DeptCode.BD: "Business Development",
    DeptCode.SAL: "Sales",
    DeptCode.EXO: "CEO Office",
    DeptCode.TBS: "Technical Bidding & Solutions",
    DeptCode.CBS: "Commercial Bidding & Solutions",
    DeptCode.QUA: "Quality",
    DeptCode.CEO: "Executive",
}


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_CLOSURE = "PENDING_CLOSURE"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class Priority(StrEnum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class AuditEvent(StrEnum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESUMED = "RESUMED"
    UPDATED = "UPDATED"
    CLOSURE_REQUESTED = "CLOSURE_REQUESTED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"
    NOTIFIED = "NOTIFIED"
