"""Ephemeral draft storage before confirmation (FR-WF-05)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from ltm.domain.models import TaskCreateDraft

_DRAFT_TTL_SECONDS = 30 * 60
_MAX_DRAFTS = 500


@dataclass(frozen=True)
class _DraftEntry:
    draft: TaskCreateDraft
    requester_entra_id: str
    expires_at: float


_drafts_by_id: dict[str, _DraftEntry] = {}


def _purge_expired() -> None:
    now = time.monotonic()
    for draft_id, entry in list(_drafts_by_id.items()):
        if entry.expires_at <= now:
            _drafts_by_id.pop(draft_id, None)
    while len(_drafts_by_id) >= _MAX_DRAFTS:
        _drafts_by_id.pop(next(iter(_drafts_by_id)))


class DraftAccessError(PermissionError):
    """Raised when a user attempts to act on another requester's draft."""


def stash_draft(draft: TaskCreateDraft, requester_entra_id: str) -> str:
    _purge_expired()
    draft_id = secrets.token_hex(6)
    _drafts_by_id[draft_id] = _DraftEntry(
        draft=draft,
        requester_entra_id=requester_entra_id,
        expires_at=time.monotonic() + _DRAFT_TTL_SECONDS,
    )
    return draft_id


def _owned_entry(draft_id: str, requester_entra_id: str) -> _DraftEntry | None:
    _purge_expired()
    entry = _drafts_by_id.get(draft_id)
    if entry is not None and entry.requester_entra_id != requester_entra_id:
        raise DraftAccessError("Only the requester who prepared this draft can act on it.")
    return entry


def take_draft(draft_id: str, requester_entra_id: str) -> TaskCreateDraft | None:
    entry = _owned_entry(draft_id, requester_entra_id)
    if entry is None:
        return None
    _drafts_by_id.pop(draft_id, None)
    return entry.draft


def peek_draft(draft_id: str, requester_entra_id: str) -> TaskCreateDraft | None:
    entry = _owned_entry(draft_id, requester_entra_id)
    return entry.draft if entry else None


def discard_draft(draft_id: str, requester_entra_id: str) -> bool:
    entry = _owned_entry(draft_id, requester_entra_id)
    if entry is None:
        return False
    _drafts_by_id.pop(draft_id, None)
    return True
