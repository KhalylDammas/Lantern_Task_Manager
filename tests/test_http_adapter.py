from __future__ import annotations

from ltm.bot.http_adapter import sanitize_activity_body


def test_sanitize_adds_missing_channel_data_for_conversation_update() -> None:
    payload = {
        "type": "conversationUpdate",
        "id": "abc",
        "channelId": "msteams",
        "from": {"id": "user-1"},
        "recipient": {"id": "bot-1"},
        "conversation": {"id": "conv-1"},
    }

    sanitized = sanitize_activity_body(payload)

    assert sanitized["channelData"] == {}


def test_sanitize_filters_unsupported_message_entities() -> None:
    payload = {
        "type": "message",
        "entities": [
            {"type": "ClientCapabilities", "supportsTts": True},
            {"type": "mention", "mentioned": {"id": "29:user"}, "text": "<at>User</at>"},
            {"type": "clientInfo", "locale": "en-US"},
        ],
    }

    sanitized = sanitize_activity_body(payload)

    assert sanitized["entities"] == [
        {"type": "mention", "mentioned": {"id": "29:user"}, "text": "<at>User</at>"},
        {"type": "clientInfo", "locale": "en-US"},
    ]


def test_sanitize_preserves_non_activity_fields() -> None:
    payload = {
        "type": "message",
        "text": "hello",
        "channelData": {"tenant": {"id": "tenant-1"}},
        "entities": None,
    }

    sanitized = sanitize_activity_body(payload)

    assert sanitized == payload
