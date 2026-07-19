"""Deterministic chat command helpers (manifest prompt starters)."""

from __future__ import annotations

from typing import Literal

from ltm.domain.models import ListTasksParams, TaskRecord
from ltm.storage.db import session_scope
from ltm.storage.repository import TaskRepository

ListFilter = Literal["my_tasks", "my_requests", "my_overdue", "my_pending_verification"]

TaskListVariant = Literal[
    "my_tasks",
    "my_requests",
    "my_overdue",
    "my_pending_verification",
    "daily_summary",
    "department",
    "all_overdue",
    "pending_verification",
]

MY_TASKS_COMMANDS = frozenset({"my tasks", "list my tasks", "/my tasks"})
MY_REQUESTS_COMMANDS = frozenset({"my requests", "list my requests", "/my requests"})
MY_OVERDUE_COMMANDS = frozenset({"overdue", "my overdue", "list overdue", "/overdue"})
MY_PENDING_VERIFICATION_COMMANDS = frozenset(
    {"pending verification", "my pending verification", "awaiting verification", "/pending verification"}
)

_TASK_LIST_TITLES: dict[TaskListVariant, str] = {
    "my_tasks": "Tasks assigned to you",
    "my_requests": "Tasks you requested",
    "my_overdue": "Your overdue tasks",
    "my_pending_verification": "Your requests awaiting verification",
    "daily_summary": "Your open tasks",
    "department": "Tasks",
    "all_overdue": "Overdue tasks",
    "pending_verification": "Tasks awaiting verification",
}


def task_list_title(variant: TaskListVariant | str) -> str:
    return _TASK_LIST_TITLES.get(variant, "Tasks")  # type: ignore[arg-type]


def _shows_assignee_in_list(variant: TaskListVariant | str) -> bool:
    return variant in {
        "my_requests",
        "my_pending_verification",
        "department",
        "all_overdue",
        "pending_verification",
    }


def _shows_priority_in_list(variant: TaskListVariant | str) -> bool:
    return variant in {"my_tasks", "my_overdue", "daily_summary"}


_TASK_LIST_MAX_ROWS = 40
_TASK_DESC_SNIPPET = 80


def _escape_md_cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ").strip()


def _due_text(task: TaskRecord) -> str:
    due = str(task.due_date)
    if task.is_overdue:
        return f"**{due}***"
    return due


def _task_cell_md(task: TaskRecord) -> str:
    title = _escape_md_cell(task.task_type)
    desc = task.description.strip()
    if not desc:
        return f"**{title}**"
    snippet = desc[:_TASK_DESC_SNIPPET] + ("…" if len(desc) > _TASK_DESC_SNIPPET else "")
    return f"**{title}**<br>_{_escape_md_cell(snippet)}_"


def _table_headers(variant: TaskListVariant | str) -> list[str]:
    headers = ["ID", "Task", "Status", "Due"]
    if _shows_assignee_in_list(variant):
        headers.insert(2, "Assignee")
    if _shows_priority_in_list(variant):
        headers.append("Priority")
    return headers


def _table_row(task: TaskRecord, variant: TaskListVariant | str) -> list[str]:
    row = [
        f"`{task.id}`",
        _task_cell_md(task),
        _escape_md_cell(str(task.status)),
        _due_text(task),
    ]
    if _shows_assignee_in_list(variant):
        assignee = task.assigned_to.display_name or task.assigned_to.entra_object_id
        row.insert(2, _escape_md_cell(assignee))
    if _shows_priority_in_list(variant):
        row.append(_escape_md_cell(str(task.priority)))
    return row


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    header_row = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(cells) + " |" for cells in rows]
    return "\n".join([header_row, separator, *body])


def format_task_list_message(*, tasks: list[TaskRecord], variant: TaskListVariant | str) -> str:
    """Markdown pipe table for Teams chat."""
    title = task_list_title(variant)
    if not tasks:
        return f"**{title}** — no matching open tasks."

    visible = tasks[:_TASK_LIST_MAX_ROWS]
    headers = _table_headers(variant)
    rows = [_table_row(task, variant) for task in visible]
    table = _markdown_table(headers, rows)

    parts = [f"**{title}** ({len(tasks)})", "", table]
    if len(tasks) > _TASK_LIST_MAX_ROWS:
        parts.append(f"\nShowing first {_TASK_LIST_MAX_ROWS} of {len(tasks)} tasks.")
    parts.append("\nAsk in natural language for details, or reference a task ID from the list.")
    return "\n".join(parts)


def match_list_filter(text: str) -> ListFilter | None:
    lowered = text.strip().lower()
    if lowered in MY_TASKS_COMMANDS:
        return "my_tasks"
    if lowered in MY_REQUESTS_COMMANDS:
        return "my_requests"
    if lowered in MY_OVERDUE_COMMANDS:
        return "my_overdue"
    if lowered in MY_PENDING_VERIFICATION_COMMANDS:
        return "my_pending_verification"
    return None


def fetch_task_list(*, viewer_entra_id: str, filter_name: ListFilter, limit: int = 25) -> list[TaskRecord]:
    params = ListTasksParams(filter=filter_name, limit=limit)
    with session_scope() as session:
        repo = TaskRepository(session)
        return repo.list_tasks(params, viewer_entra_id)
