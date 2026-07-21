"""Durable, revisioned task drafts awaiting explicit confirmation."""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ltm.domain.business_time import business_now
from ltm.domain.models import TaskCreateDraft
from ltm.storage.db import session_scope
from ltm.storage.orm import TaskDraftORM

_DRAFT_TTL = timedelta(minutes=30)


class DraftAccessError(PermissionError):
    """Raised when a user attempts to act on another requester's draft."""


def stash_draft(draft: TaskCreateDraft, requester_entra_id: str) -> str:
    draft_id = secrets.token_hex(8)
    with session_scope() as session:
        session.add(TaskDraftORM(
            draft_id=draft_id,
            requester_entra_id=requester_entra_id,
            payload=draft.model_dump(mode="json"),
            revision=1,
            state="ACTIVE",
            expires_at=business_now() + _DRAFT_TTL,
        ))
    return draft_id


def _owned_row(session, draft_id: str, requester_entra_id: str) -> TaskDraftORM | None:
    row = session.scalar(select(TaskDraftORM).where(TaskDraftORM.draft_id == draft_id))
    if row is not None and row.requester_entra_id != requester_entra_id:
        raise DraftAccessError("Only the requester who prepared this draft can act on it.")
    expires_at = row.expires_at if row is not None else None
    now = business_now()
    if expires_at is not None and expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    if row is None or row.state != "ACTIVE" or (expires_at is not None and expires_at <= now):
        if row is not None and row.state == "ACTIVE":
            row.state = "CANCELLED"
        return None
    return row


def take_draft(draft_id: str, requester_entra_id: str) -> TaskCreateDraft | None:
    """Atomically consume the latest active draft exactly once."""
    with session_scope() as session:
        return take_draft_in_session(session, draft_id, requester_entra_id)


def take_draft_in_session(
    session: Session,
    draft_id: str,
    requester_entra_id: str,
) -> TaskCreateDraft | None:
    """Claim a draft inside the caller's transaction."""
    row = _owned_row(session, draft_id, requester_entra_id)
    if row is None:
        return None
    payload = dict(row.payload)
    claimed = session.execute(
        update(TaskDraftORM)
        .where(TaskDraftORM.draft_id == draft_id, TaskDraftORM.state == "ACTIVE")
        .values(state="CONSUMED", updated_at=business_now())
    )
    if claimed.rowcount != 1:
        return None
    return TaskCreateDraft.model_validate(payload)


def peek_draft(draft_id: str, requester_entra_id: str) -> TaskCreateDraft | None:
    with session_scope() as session:
        row = _owned_row(session, draft_id, requester_entra_id)
        return TaskCreateDraft.model_validate(row.payload) if row else None


def completed_draft_task_id(draft_id: str, requester_entra_id: str) -> str | None:
    with session_scope() as session:
        row = session.get(TaskDraftORM, draft_id)
        if row is not None and row.requester_entra_id != requester_entra_id:
            raise DraftAccessError("Only the requester who prepared this draft can act on it.")
        if row is None or row.state != "CONSUMED":
            return None
        return str((row.payload or {}).get("_task_id") or "") or None


def record_draft_task_id(session: Session, draft_id: str, task_id: str) -> None:
    row = session.get(TaskDraftORM, draft_id)
    if row is None or row.state != "CONSUMED":
        raise RuntimeError("Consumed draft disappeared before task result was recorded")
    row.payload = {**dict(row.payload or {}), "_task_id": task_id}


def revise_draft(draft_id: str, requester_entra_id: str, draft: TaskCreateDraft) -> int | None:
    with session_scope() as session:
        row = _owned_row(session, draft_id, requester_entra_id)
        if row is None:
            return None
        row.payload = draft.model_dump(mode="json")
        row.revision += 1
        row.expires_at = business_now() + _DRAFT_TTL
        row.updated_at = business_now()
        return row.revision


def discard_draft(draft_id: str, requester_entra_id: str) -> bool:
    with session_scope() as session:
        row = _owned_row(session, draft_id, requester_entra_id)
        if row is None:
            return False
        row.state = "CANCELLED"
        row.updated_at = business_now()
        return True
