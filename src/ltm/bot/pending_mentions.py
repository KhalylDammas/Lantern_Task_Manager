"""Conversation-scoped state for assignee disambiguation cards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ltm.bot.mentions import MentionResolution
from ltm.domain.models import UserRef
from ltm.interaction.models import InteractionOperation
from ltm.interaction.store import InteractionStore
SourceKind = Literal["message"]


@dataclass
class PendingDisambiguation:
    pick_id: str
    conversation_id: str
    token: str
    query: str
    candidates: tuple[MentionResolution, ...]
    source: SourceKind
    original_message: str = ""


_fallback_pending_by_pick_id: dict[str, PendingDisambiguation] = {}
_conversation_overrides: dict[str, dict[str, MentionResolution]] = {}


def stash_pending_disambiguation(
    *,
    conversation_id: str,
    token: str,
    query: str,
    candidates: tuple[MentionResolution, ...],
    source: SourceKind,
    original_message: str = "",
    actor_id: str,
    expected_revision: int | None = None,
) -> str:
    import secrets

    pick_id = secrets.token_hex(6)
    store = InteractionStore()
    if not store.enabled():
        _fallback_pending_by_pick_id[pick_id] = PendingDisambiguation(
            pick_id=pick_id, conversation_id=conversation_id, token=token, query=query,
            candidates=candidates, source=source, original_message=original_message)
        return pick_id
    stored = store.set_pending(
        actor_id=actor_id,
        conversation_id=conversation_id,
        operation=InteractionOperation.CREATE_TASK,
        reference_id=pick_id,
        missing_fields=["assignee"],
        expected_revision=expected_revision,
        slots={
            "disambiguation": True,
            "token": token,
            "query": query,
            "source": source,
            "original_message": original_message,
            "candidates": [{
                "token": candidate.token,
                "user": candidate.user.model_dump(mode="json"),
                "mail": candidate.mail,
                "upn": candidate.upn,
                "job_title": candidate.job_title,
            } for candidate in candidates],
        },
    )
    return pick_id if stored is not None or not store.enabled() else ""


def take_pending_disambiguation(
    pick_id: str,
    *,
    actor_id: str,
    conversation_id: str,
) -> PendingDisambiguation | None:
    store = InteractionStore()
    if not store.enabled():
        return _fallback_pending_by_pick_id.pop(pick_id, None)
    row = store.get(actor_id=actor_id, conversation_id=conversation_id)
    if row is None or row.reference_id != pick_id or not row.slots.get("disambiguation"):
        return None
    candidates = tuple(MentionResolution(
        token=str(candidate.get("token") or ""),
        user=UserRef.model_validate(candidate.get("user") or {}),
        mail=str(candidate.get("mail") or ""),
        upn=str(candidate.get("upn") or ""),
        job_title=str(candidate.get("job_title") or ""),
    ) for candidate in row.slots.get("candidates") or [])
    store.clear(actor_id=actor_id, conversation_id=conversation_id)
    return PendingDisambiguation(
        pick_id=pick_id,
        conversation_id=conversation_id,
        token=str(row.slots.get("token") or ""),
        query=str(row.slots.get("query") or ""),
        candidates=candidates,
        source="message",
        original_message=str(row.slots.get("original_message") or ""),
    )


def set_mention_override(conversation_id: str, token: str, resolution: MentionResolution) -> None:
    bucket = _conversation_overrides.setdefault(conversation_id, {})
    bucket[token] = resolution


def get_mention_overrides(conversation_id: str) -> dict[str, MentionResolution]:
    return dict(_conversation_overrides.get(conversation_id, {}))


def clear_mention_overrides(conversation_id: str) -> None:
    _conversation_overrides.pop(conversation_id, None)


def clear_conversation_pending(conversation_id: str) -> None:
    for pick_id, pending in list(_fallback_pending_by_pick_id.items()):
        if pending.conversation_id == conversation_id:
            _fallback_pending_by_pick_id.pop(pick_id, None)
    clear_mention_overrides(conversation_id)
