"""Teams conversation context (draft confirmation queue)."""

from __future__ import annotations

import json
from contextvars import ContextVar

from ltm.domain.models import TaskCreateDraft

conversation_id_ctx: ContextVar[str | None] = ContextVar("conversation_id", default=None)

# Latest draft per conversation awaiting Adaptive Card confirm (FR-WF-05)
_pending_confirm: dict[str, TaskCreateDraft] = {}


def remember_draft(conversation_id: str | None, draft: TaskCreateDraft) -> None:
    if not conversation_id:
        return
    _pending_confirm[conversation_id] = draft


def pop_draft(conversation_id: str | None) -> TaskCreateDraft | None:
    if not conversation_id:
        return None
    return _pending_confirm.pop(conversation_id, None)


def peek_draft(conversation_id: str | None) -> TaskCreateDraft | None:
    if not conversation_id:
        return None
    return _pending_confirm.get(conversation_id)
