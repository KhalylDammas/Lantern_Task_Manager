"""Build Adaptive Cards as dicts / Pydantic AdaptiveCard (C01, C14)."""

from __future__ import annotations

from microsoft_teams.cards import AdaptiveCard

from ltm.bot.help_text import welcome_card_body_text, welcome_card_suggestions_text
from ltm.bot.mentions import MentionResolution, department_code
from ltm.domain.enums import Priority

PRIORITY_CHOICES = [
    {"title": priority.value, "value": priority.value}
    for priority in (Priority.CRITICAL, Priority.HIGH, Priority.MEDIUM, Priority.LOW)
]

ASSIGNEE_DEPT_CHOICES = [
    {"title": "FIN", "value": "FIN"},
    {"title": "PROC", "value": "PROC"},
    {"title": "PROJ", "value": "PROJ"},
    {"title": "HR", "value": "HR"},
    {"title": "IT", "value": "IT"},
]


def _candidate_label(candidate: MentionResolution) -> str:
    name = candidate.user.display_name or candidate.token[1:]
    dept = candidate.user.department or department_code(candidate.user.department)
    email = candidate.mail or candidate.upn
    parts = [name]
    if dept:
        parts.append(dept)
    if email:
        parts.append(email)
    return " — ".join(parts)


def draft_confirm_payload(
    *,
    draft_id: str,
    task_type: str,
    assignee: str,
    due: str,
    priority: str,
    description: str,
    po: str | None = None,
    assignee_department: str | None = None,
    assignee_mail: str | None = None,
    assignee_job_title: str | None = None,
) -> dict:
    facts = [
        {"title": "Draft reference", "value": draft_id},
        {"title": "Type", "value": task_type},
        {"title": "Assignee", "value": assignee},
        {"title": "Due", "value": due},
        {"title": "Priority", "value": priority},
    ]
    if assignee_department:
        facts.append({"title": "Department", "value": assignee_department})
    if assignee_mail:
        facts.append({"title": "Email", "value": assignee_mail})
    if assignee_job_title:
        facts.append({"title": "Job title", "value": assignee_job_title})
    if po:
        facts.append({"title": "PO", "value": po})

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Confirm new task", "weight": "Bolder", "size": "Medium"},
            {"type": "FactSet", "facts": facts},
            {
                "type": "TextBlock",
                "text": description[:500] + ("…" if len(description) > 500 else ""),
                "wrap": True,
            },
            {"type": "TextBlock", "text": "D365-linked fields are read-only reference.", "isSubtle": True, "wrap": True},
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Confirm",
                "verb": "draft.confirm",
                "data": {"draft_id": draft_id},
            },
            {
                "type": "Action.Execute",
                "title": "Cancel",
                "verb": "draft.cancel",
                "data": {"draft_id": draft_id},
            },
        ],
    }


def draft_confirm_card(**kwargs) -> AdaptiveCard:
    return AdaptiveCard.model_validate(draft_confirm_payload(**kwargs))


def assignee_disambiguation_card(
    *,
    pick_id: str,
    token: str,
    query: str,
    candidates: tuple[MentionResolution, ...],
    source: str = "message",
) -> AdaptiveCard:
    choices = [
        {
            "title": _candidate_label(candidate),
            "value": candidate.user.entra_object_id,
        }
        for candidate in candidates
    ]
    payload: dict = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Choose assignee", "weight": "Bolder"},
            {
                "type": "TextBlock",
                "text": f"Multiple directory matches for {token} ({query}). Pick the correct person.",
                "wrap": True,
            },
            {
                "type": "Input.ChoiceSet",
                "id": "assignee_entra_id",
                "label": "Assignee",
                "isRequired": True,
                "choices": choices,
            },
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Continue",
                "verb": "pick_assignee",
                "data": {"pick_id": pick_id, "token": token, "source": source},
            }
        ],
    }
    return AdaptiveCard.model_validate(payload)


def manual_task_form_card() -> AdaptiveCard:
    """Structured capture when NL/LLM path is unavailable (FR-AI-04)."""
    d: dict = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Create task (manual)", "weight": "Bolder"},
            {
                "type": "TextBlock",
                "text": "Submit to review a confirmation card before the task is created.",
                "isSubtle": True,
                "wrap": True,
            },
            {"type": "Input.Text", "id": "task_type", "label": "Task type", "isRequired": True},
            {"type": "Input.Text", "id": "description", "label": "Description", "isMultiline": True, "isRequired": True},
            {
                "type": "Input.Text",
                "id": "assignee_name",
                "label": "Assignee name",
                "placeholder": "e.g. Alice Jones",
                "isRequired": True,
            },
            {
                "type": "Input.ChoiceSet",
                "id": "assignee_department_code",
                "label": "Assignee dept code",
                "style": "compact",
                "isRequired": True,
                "choices": ASSIGNEE_DEPT_CHOICES,
            },
            {
                "type": "Input.ChoiceSet",
                "id": "priority",
                "label": "Priority",
                "value": Priority.MEDIUM.value,
                "choices": PRIORITY_CHOICES,
            },
            {"type": "Input.Date", "id": "due_date", "label": "Due date"},
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Submit",
                "verb": "manual_create_submit",
                "data": {},
            }
        ],
    }
    return AdaptiveCard.model_validate(d)


def manager_verification_card(*, task_id: str, summary: str) -> AdaptiveCard:
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Verify task completion", "weight": "Bolder"},
            {"type": "TextBlock", "text": f"Task {task_id}", "weight": "Bolder", "wrap": True},
            {"type": "TextBlock", "text": summary[:800], "wrap": True},
            {"type": "Input.Text", "id": "rejection_reason", "label": "Reject reason (required if rejecting)", "isMultiline": True},
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Confirm complete",
                "verb": "task.verify",
                "data": {"task_id": task_id},
            },
            {
                "type": "Action.Execute",
                "title": "Reject",
                "verb": "task.reject",
                "data": {"task_id": task_id},
            },
        ],
    }
    return AdaptiveCard.model_validate(d)


def task_detail_card(
    *,
    task_id: str,
    task_type: str,
    status: str,
    due: str,
    priority: str,
    assignee_name: str,
    created_by_name: str,
    description: str,
    description_max: int = 280,
) -> AdaptiveCard:
    """Compact read-only task summary for card-action View details."""
    desc = description.strip()
    if len(desc) > description_max:
        desc = desc[:description_max].rstrip() + "…"
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": task_id, "weight": "Bolder", "size": "Medium", "wrap": True},
            {"type": "TextBlock", "text": task_type, "isSubtle": True, "wrap": True},
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Status", "value": status},
                    {"title": "Due", "value": due},
                    {"title": "Priority", "value": priority},
                    {"title": "Assignee", "value": assignee_name},
                    {"title": "Created by", "value": created_by_name},
                ],
            },
        ],
    }
    if desc:
        d["body"].append({"type": "TextBlock", "text": desc, "wrap": True, "spacing": "Medium"})
    return AdaptiveCard.model_validate(d)


def task_assignment_card(
    *,
    task_id: str,
    task_type: str,
    description: str,
    due: str,
    priority: str,
    created_by_name: str,
) -> AdaptiveCard:
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "New task assigned to you", "weight": "Bolder", "size": "Medium"},
            {"type": "TextBlock", "text": f"{task_id} — {task_type}", "weight": "Bolder", "wrap": True},
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Due", "value": due},
                    {"title": "Priority", "value": priority},
                    {"title": "Created by", "value": created_by_name},
                ],
            },
            {
                "type": "TextBlock",
                "text": description[:500] + ("…" if len(description) > 500 else ""),
                "wrap": True,
            },
            {
                "type": "Input.Text",
                "id": "completion_notes",
                "label": "Completion notes (required when closing)",
                "isMultiline": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Acknowledge",
                "verb": "task.acknowledge",
                "data": {"task_id": task_id},
            },
            {
                "type": "Action.Execute",
                "title": "View details",
                "verb": "task.view",
                "data": {"task_id": task_id},
            },
            {
                "type": "Action.Execute",
                "title": "Close task",
                "verb": "task.close",
                "data": {"task_id": task_id},
            },
        ],
    }
    return AdaptiveCard.model_validate(d)


def task_reopened_card(*, task_id: str, reason: str) -> AdaptiveCard:
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Task reopened", "weight": "Bolder"},
            {"type": "TextBlock", "text": f"Task {task_id} needs more work.", "weight": "Bolder", "wrap": True},
            {"type": "TextBlock", "text": reason[:800], "wrap": True},
            {
                "type": "Input.Text",
                "id": "completion_notes",
                "label": "Completion notes (required when closing)",
                "isMultiline": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Resume work",
                "verb": "task.resume",
                "data": {"task_id": task_id},
            },
            {
                "type": "Action.Execute",
                "title": "View task",
                "verb": "task.view",
                "data": {"task_id": task_id},
            },
            {
                "type": "Action.Execute",
                "title": "Close task",
                "verb": "task.close",
                "data": {"task_id": task_id},
            },
        ],
    }
    return AdaptiveCard.model_validate(d)


def task_status_card(*, task_id: str, status: str) -> AdaptiveCard:
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Task update", "weight": "Bolder"},
            {
                "type": "TextBlock",
                "text": f"{task_id} is now {status}.",
                "weight": "Bolder",
                "wrap": True,
            },
        ],
    }
    return AdaptiveCard.model_validate(d)


def welcome_card() -> AdaptiveCard:
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Welcome to Lantern Task Manager", "weight": "Bolder", "size": "Medium"},
            {
                "type": "TextBlock",
                "text": welcome_card_body_text(),
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": welcome_card_suggestions_text(),
                "wrap": True,
                "isSubtle": True,
            },
        ],
    }
    return AdaptiveCard.model_validate(d)


def overdue_escalation_card(*, task_id: str, assignee_name: str, days_overdue: int) -> AdaptiveCard:
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Overdue task escalation", "weight": "Bolder"},
            {
                "type": "TextBlock",
                "text": f"Task {task_id} for {assignee_name} is overdue by {days_overdue} day(s).",
                "weight": "Bolder",
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "View task",
                "verb": "task.view",
                "data": {"task_id": task_id},
            },
        ],
    }
    return AdaptiveCard.model_validate(d)
