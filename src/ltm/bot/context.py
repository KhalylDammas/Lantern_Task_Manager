"""Request-scoped context for tools (C04)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

from microsoft_teams.cards import AdaptiveCard

from ltm.domain.models import UserRef

conversation_id_var: ContextVar[Optional[str]] = ContextVar("conversation_id", default=None)
actor_var: ContextVar[Optional[UserRef]] = ContextVar("actor", default=None)
_pending_cards: ContextVar[Optional[list[AdaptiveCard]]] = ContextVar("pending_cards", default=None)
_terminal_response: ContextVar[Optional[str]] = ContextVar("terminal_response", default=None)
_interaction_revision: ContextVar[Optional[int]] = ContextVar("interaction_revision", default=None)


def set_turn_context(*, conversation_id: str, actor: UserRef) -> None:
    conversation_id_var.set(conversation_id)
    actor_var.set(actor)
    _pending_cards.set([])
    _terminal_response.set(None)
    _interaction_revision.set(None)


def get_actor() -> UserRef:
    a = actor_var.get()
    if not a:
        raise RuntimeError("actor not set")
    return a


def get_conversation_id() -> str:
    conversation_id = conversation_id_var.get()
    if not conversation_id:
        raise RuntimeError("conversation not set")
    return conversation_id


def set_interaction_revision(revision: int | None) -> None:
    _interaction_revision.set(revision)


def get_interaction_revision() -> int | None:
    return _interaction_revision.get()


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


def set_terminal_response(message: str) -> None:
    """Provide a complete tool response that does not need model paraphrasing."""
    from ltm.config.settings import get_settings

    if not get_settings().llm_terminal_responses_enabled:
        return
    _terminal_response.set(message)


def take_terminal_response() -> str | None:
    """Consume the current turn's terminal response, if one was produced."""
    message = _terminal_response.get()
    _terminal_response.set(None)
    return message
