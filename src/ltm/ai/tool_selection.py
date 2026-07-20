"""Conservative per-turn tool exposure to reduce repeated schema tokens."""

from __future__ import annotations

import re
from typing import Any

from microsoft_teams.ai import Function

_TASK_ID = re.compile(r"\bLTM-(?:FIN|PROC|PROJ|HR|IT|CEO)-\d{4}-\d{4}\b", re.I)
_TASK_RULES: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"\b(?:acknowledge|accept)\b", re.I), frozenset({"acknowledge_task"})),
    (re.compile(r"\b(?:close|complete|completed|done)\b", re.I), frozenset({"close_task"})),
    (re.compile(r"\b(?:verify|approve)\b", re.I), frozenset({"verify_task"})),
    (re.compile(r"\b(?:reopen|reject)\b", re.I), frozenset({"reopen_task"})),
    (re.compile(r"\bresume\b", re.I), frozenset({"resume_task"})),
)
_GENERAL_RULES: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"\b(?:status|details?)\b", re.I), frozenset({"get_task_status"})),
    (re.compile(r"\b(?:list|show)\b.*\btasks?\b", re.I), frozenset({"list_tasks"})),
    (re.compile(r"\bconfirm\b.*\bdraft\b", re.I), frozenset({"confirm_task_draft"})),
    (re.compile(r"\bcancel\b.*\bdraft\b", re.I), frozenset({"cancel_task_draft"})),
)


def select_tools_for_message(functions: list[Function[Any]], message: str) -> list[Function[Any]]:
    """Narrow only high-confidence intents; otherwise preserve every capability."""
    rules = (*(_TASK_RULES if _TASK_ID.search(message) else ()), *_GENERAL_RULES)
    for pattern, names in rules:
        if pattern.search(message):
            selected = [function for function in functions if function.name in names]
            return selected or functions
    return functions
