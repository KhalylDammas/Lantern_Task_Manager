"""Build Adaptive Cards as dicts / Pydantic AdaptiveCard (C01, C14)."""

from __future__ import annotations

import secrets

from microsoft_teams.cards import AdaptiveCard

from ltm.bot.help_text import welcome_card_body_text, welcome_card_suggestions_text
from ltm.bot.mentions import MentionResolution, department_code


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
    action_token = secrets.token_hex(12)
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
                "data": {"draft_id": draft_id, "action_token": action_token},
            },
            {
                "type": "Action.Execute",
                "title": "Cancel",
                "verb": "draft.cancel",
                "data": {"draft_id": draft_id, "action_token": action_token},
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
    action_token = secrets.token_hex(12)
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
        ],
        "actions": [{
            "type": "Action.Execute",
            "title": _candidate_label(candidate),
            "verb": "pick_assignee",
            "data": {"pick_id": pick_id, "token": token, "source": source,
                     "assignee_entra_id": candidate.user.entra_object_id,
                     "action_token": action_token},
        } for candidate in candidates],
    }
    return AdaptiveCard.model_validate(payload)


def manager_verification_card(*, task_id: str, summary: str) -> AdaptiveCard:
    action_token = secrets.token_hex(12)
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Verify task completion", "weight": "Bolder"},
            {"type": "TextBlock", "text": f"Task {task_id}", "weight": "Bolder", "wrap": True},
            {"type": "TextBlock", "text": summary[:800], "wrap": True},
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Confirm complete",
                "verb": "task.verify",
                "data": {"task_id": task_id, "action_token": action_token},
            },
            {
                "type": "Action.Execute",
                "title": "Reopen",
                "verb": "task.reject",
                "data": {"task_id": task_id, "action_token": action_token},
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
    action_token = secrets.token_hex(12)
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
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Acknowledge",
                "verb": "task.acknowledge",
                "data": {"task_id": task_id, "action_token": action_token},
            },
            {
                "type": "Action.Execute",
                "title": "View details",
                "verb": "task.view",
                "data": {"task_id": task_id, "action_token": action_token},
            },
            {
                "type": "Action.Execute",
                "title": "Close task",
                "verb": "task.close",
                "data": {"task_id": task_id, "action_token": action_token},
            },
        ],
    }
    return AdaptiveCard.model_validate(d)


def task_reopened_card(*, task_id: str, reason: str) -> AdaptiveCard:
    action_token = secrets.token_hex(12)
    d = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Task reopened", "weight": "Bolder"},
            {"type": "TextBlock", "text": f"Task {task_id} needs more work.", "weight": "Bolder", "wrap": True},
            {"type": "TextBlock", "text": reason[:800], "wrap": True},
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Resume work",
                "verb": "task.resume",
                "data": {"task_id": task_id, "action_token": action_token},
            },
            {
                "type": "Action.Execute",
                "title": "View task",
                "verb": "task.view",
                "data": {"task_id": task_id, "action_token": action_token},
            },
            {
                "type": "Action.Execute",
                "title": "Close task",
                "verb": "task.close",
                "data": {"task_id": task_id, "action_token": action_token},
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
    action_token = secrets.token_hex(12)
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
                "data": {"task_id": task_id, "action_token": action_token},
            },
        ],
    }
    return AdaptiveCard.model_validate(d)
