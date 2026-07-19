"""Conversation binding persistence (C03/C04 wiring)."""

from __future__ import annotations

from microsoft_teams.api import Account, ConversationAccount, ConversationReference

from ltm.storage.conversation_bindings import ConversationBindingRepository
from ltm.storage.db import session_scope


def _sample_ref(uid: str) -> ConversationReference:
    return ConversationReference(
        bot=Account(id="bot-app-id", name="Bot"),
        user=Account(id="29:user", name="User", aad_object_id=uid),
        conversation=ConversationAccount(id="conversation-1", conversation_type="personal"),
        channel_id="msteams",
        service_url="https://example.local/",
        locale="en-US",
        activity_id="act-1",
    )


def test_conversation_binding_roundtrip() -> None:
    oid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ref = _sample_ref(oid)
    with session_scope() as session:
        ConversationBindingRepository(session).upsert(oid, ref)
    with session_scope() as session2:
        back = ConversationBindingRepository(session2).get_ref(oid)
        assert back is not None
        assert back.bot.id == "bot-app-id"
        assert back.user and back.user.aad_object_id == oid
        assert back.conversation.id == "conversation-1"
