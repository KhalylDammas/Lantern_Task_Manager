"""Shared help and welcome copy for LTM Teams surfaces."""

from __future__ import annotations

HELP_COMMANDS = (
    "**help** — show this guide",
    "**form** — open the structured task creation card",
    "**my tasks** — list tasks assigned to you",
    "**my requests** — list tasks you created for others",
    "**/who** *name* — search Entra directory (requires Graph permissions)",
)

WELCOME_SUGGESTIONS = "**help**, **my tasks**, **my requests**, or **form**"


def help_message_text(*, graph_enabled: bool) -> str:
    lines = [
        "**Lantern Task Manager (LTM)** — personal task lifecycle assistant for Lantern Systems.",
        "",
        "**Natural language** — create and assign tasks, close with completion notes, search status, "
        "and (when enabled) read-only D365 lookups for PO, vendor, invoice, customer, or project references.",
        "",
        "**Shortcuts**",
        *[f"- {line}" for line in HELP_COMMANDS],
        "",
        "**@mentions** — assign someone with **@Display Name** when directory search is enabled.",
        "",
        "**Confirm in chat is not enough** — new tasks save only after you click **Confirm** on the Adaptive Card.",
        "",
        "**Verifiers** — confirm or reopen tasks from the verification card, or ask in chat to reopen a task (a reason is required).",
        "**Assignees** — acknowledge new tasks, close completed work, and resume reopened tasks from a card or by asking in chat.",
        "",
        "LTM tracks operational tasks; it does not write to Dynamics 365 or perform ERP work.",
    ]
    if not graph_enabled:
        lines.extend(
            [
                "",
                "_Directory search (/who, @mentions) is unavailable in this environment._",
            ]
        )
    return "\n".join(lines)


def welcome_card_body_text() -> str:
    return (
        "Create and track tasks in natural language, confirm assignments with Adaptive Cards, "
        "and receive proactive updates here and in your Activity feed."
    )


def welcome_card_suggestions_text() -> str:
    return f"Try {WELCOME_SUGGESTIONS}."


def welcome_bot_text() -> str:
    return f"Welcome to Lantern Task Manager. Type **help** for shortcuts, or try {WELCOME_SUGGESTIONS}."
