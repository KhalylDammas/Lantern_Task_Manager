"""Request-scoped context for tools (C04)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

from microsoft_teams.cards import AdaptiveCard

from ltm.domain.models import UserRef

conversation_id_var: ContextVar[Optional[str]] = ContextVar("conversation_id", default=None)
actor_var: ContextVar[Optional[UserRef]] = ContextVar("actor", default=None)
_pending_cards: ContextVar[Optional[list[AdaptiveCard]]] = ContextVar("pending_cards", default=None)


def set_turn_context(*, conversation_id: str, actor: UserRef) -> None:
    conversation_id_var.set(conversation_id)
    actor_var.set(actor)
    _pending_cards.set([])


def get_actor() -> UserRef:
    a = actor_var.get()
    if not a:
        raise RuntimeError("actor not set")
    return a


def push_pending_card(card: AdaptiveCard) -> None:
    cur = _pending_cards.get()
    if cur is None:
        cur = []
    cur.append(card)
    _pending_cards.set(cur)


def drain_pending_cards() -> list[AdaptiveCard]:
    cur = _pending_cards.get()
    _pending_cards.set([])
    return cur or []
