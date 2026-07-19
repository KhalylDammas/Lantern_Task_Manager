"""Conversation-scoped state for assignee disambiguation cards."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any, Literal

from ltm.bot.mentions import MentionResolution
from ltm.domain.models import TaskCreateDraft

SourceKind = Literal["message", "manual_form"]


@dataclass
class PendingDisambiguation:
    pick_id: str
    conversation_id: str
    token: str
    query: str
    candidates: tuple[MentionResolution, ...]
    source: SourceKind
    original_message: str = ""
    manual_form_fields: dict[str, Any] = field(default_factory=dict)


_pending_by_pick_id: dict[str, PendingDisambiguation] = {}
_conversation_overrides: dict[str, dict[str, MentionResolution]] = {}


def stash_pending_disambiguation(
    *,
    conversation_id: str,
    token: str,
    query: str,
    candidates: tuple[MentionResolution, ...],
    source: SourceKind,
    original_message: str = "",
    manual_form_fields: dict[str, Any] | None = None,
) -> str:
    pick_id = secrets.token_hex(6)
    _pending_by_pick_id[pick_id] = PendingDisambiguation(
        pick_id=pick_id,
        conversation_id=conversation_id,
        token=token,
        query=query,
        candidates=candidates,
        source=source,
        original_message=original_message,
        manual_form_fields=dict(manual_form_fields or {}),
    )
    return pick_id


def take_pending_disambiguation(pick_id: str) -> PendingDisambiguation | None:
    return _pending_by_pick_id.pop(pick_id, None)


def set_mention_override(conversation_id: str, token: str, resolution: MentionResolution) -> None:
    bucket = _conversation_overrides.setdefault(conversation_id, {})
    bucket[token] = resolution


def get_mention_overrides(conversation_id: str) -> dict[str, MentionResolution]:
    return dict(_conversation_overrides.get(conversation_id, {}))


def clear_mention_overrides(conversation_id: str) -> None:
    _conversation_overrides.pop(conversation_id, None)


def clear_conversation_pending(conversation_id: str) -> None:
    to_remove = [pid for pid, pending in _pending_by_pick_id.items() if pending.conversation_id == conversation_id]
    for pick_id in to_remove:
        _pending_by_pick_id.pop(pick_id, None)
    clear_mention_overrides(conversation_id)


def build_manual_draft(fields: dict[str, Any], assignee: MentionResolution) -> TaskCreateDraft:
    from datetime import date

    from ltm.domain.enums import DeptCode, Priority

    raw_due = str(fields.get("due_date") or "")
    dept_raw = str(fields.get("assignee_department_code") or "").strip().upper()
    dept_code = DeptCode(dept_raw or department_code_from_mention(assignee))
    return TaskCreateDraft(
        task_type=str(fields.get("task_type") or "").strip(),
        description=str(fields.get("description") or "").strip(),
        assignee_entra_id=assignee.user.entra_object_id,
        assignee_display_name=assignee.user.display_name or assignee.token[1:],
        assignee_department=assignee.user.department,
        assignee_department_code=dept_code,
        priority=Priority(str(fields.get("priority") or Priority.MEDIUM.value)),
        due_date=date.fromisoformat(raw_due[:10]),
    )


def department_code_from_mention(mention: MentionResolution) -> str:
    from ltm.bot.mentions import department_code

    code = department_code(mention.user.department)
    return code or "FIN"
