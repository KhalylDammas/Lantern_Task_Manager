from __future__ import annotations

import json

import pytest

from ltm.ai.turn_payload import (
    build_turn_payload,
    extract_task_references,
    serialize_turn_payload,
)


class DummyConversation:
    def __init__(
        self,
        *,
        conversation_id: str = "conv-1",
        conversation_type: str = "personal",
        is_group: bool = False,
    ) -> None:
        self.id = conversation_id
        self.conversation_type = conversation_type
        self.is_group = is_group


class DummySender:
    def __init__(
        self,
        *,
        entra_id: str = "entra-requester",
        name: str = "Requester User",
        bot_id: str = "29:requester",
    ) -> None:
        self.id = bot_id
        self.aad_object_id = entra_id
        self.name = name


class DummyActivity:
    def __init__(
        self,
        text: str,
        *,
        entities: list[object] | None = None,
        activity_id: str = "activity-1",
        sender: DummySender | None = None,
        conversation: DummyConversation | None = None,
    ) -> None:
        self.text = text
        self.entities = entities
        self.id = activity_id
        self.from_ = sender or DummySender()
        self.conversation = conversation or DummyConversation()


async def _single_user_search(query: str) -> list[dict[str, str]]:
    if query == "Alice Jones":
        return [
            {
                "entra_object_id": "entra-alice",
                "display_name": "Alice Jones",
                "department": "Finance",
                "mail": "alice@example.com",
                "upn": "alice@example.com",
                "job_title": "Controller",
            }
        ]
    if query == "Requester User":
        return [
            {
                "entra_object_id": "entra-requester",
                "display_name": "Requester User",
                "department": "IT",
                "mail": "requester@example.com",
                "upn": "requester@example.com",
                "job_title": "Engineer",
            }
        ]
    return []


async def _ambiguous_user_search(query: str) -> list[dict[str, str]]:
    if query == "Alice":
        return [
            {
                "entra_object_id": "entra-1",
                "display_name": "Alice A",
                "department": "Finance",
                "mail": "alice.a@example.com",
            },
            {
                "entra_object_id": "entra-2",
                "display_name": "Alice B",
                "department": "IT",
                "mail": "alice.b@example.com",
            },
        ]
    return []


def test_extract_task_references_dedupes_and_preserves_order() -> None:
    message = "Close LTM-fin-2026-0001 and check LTM-FIN-2026-0002, then LTM-FIN-2026-0001 again"
    assert extract_task_references(message) == [
        "LTM-FIN-2026-0001",
        "LTM-FIN-2026-0002",
    ]


@pytest.mark.asyncio
async def test_build_turn_payload_plain_message_without_enrichments() -> None:
    activity = DummyActivity(text="Show my overdue tasks")

    payload = await build_turn_payload(activity, search_users=None, tool_profile="full")
    serialized = serialize_turn_payload(payload)
    data = json.loads(serialized)

    assert data["schema_version"] == "1"
    assert data["message"] == "Show my overdue tasks"
    assert data["actor"]["entra_object_id"] == "entra-requester"
    assert data["actor"]["display_name"] == "Requester User"
    assert data["capabilities"]["graph_enabled"] is False
    assert data["capabilities"]["tool_profile"] == "full"
    assert "enrichments" not in data


@pytest.mark.asyncio
async def test_build_turn_payload_includes_resolved_mention_enrichments() -> None:
    activity = DummyActivity(text="@Alice Jones please approve this task")

    payload = await build_turn_payload(activity, search_users=_single_user_search, tool_profile="full")
    data = json.loads(serialize_turn_payload(payload))

    assert "Directory-resolved mentioned users:" not in data["message"]
    assert data["enrichments"]["mentions"]["resolved"][0]["assignee_entra_id"] == "entra-alice"
    assert data["enrichments"]["mentions"]["resolved"][0]["assignee_department_code"] == "FIN"
    assert "ambiguous" not in data["enrichments"]["mentions"]


@pytest.mark.asyncio
async def test_build_turn_payload_includes_ambiguous_mention_enrichments() -> None:
    activity = DummyActivity(text="@Alice please approve this task")

    payload = await build_turn_payload(activity, search_users=_ambiguous_user_search, tool_profile="full")
    data = json.loads(serialize_turn_payload(payload))

    assert data["enrichments"]["mentions"]["ambiguous"][0]["token"] == "@Alice"
    assert len(data["enrichments"]["mentions"]["ambiguous"][0]["candidates"]) == 2
    assert "resolved" not in data["enrichments"]["mentions"]


@pytest.mark.asyncio
async def test_build_turn_payload_extracts_task_references() -> None:
    activity = DummyActivity(text="Please close LTM-FIN-2026-0001 with notes")

    payload = await build_turn_payload(activity, search_users=None, tool_profile="full")
    data = json.loads(serialize_turn_payload(payload))

    assert data["enrichments"]["task_references"] == ["LTM-FIN-2026-0001"]


@pytest.mark.asyncio
async def test_build_turn_payload_redacts_message_only() -> None:
    activity = DummyActivity(text="Process payment card 4111111111111111 for LTM-IT-2026-0003")

    payload = await build_turn_payload(activity, search_users=None, tool_profile="full")
    data = json.loads(serialize_turn_payload(payload))

    assert "[REDACTED_PAYMENT_IDENTIFIER]" in data["message"]
    assert data["actor"]["entra_object_id"] == "entra-requester"
    assert data["enrichments"]["task_references"] == ["LTM-IT-2026-0003"]


@pytest.mark.asyncio
async def test_build_turn_payload_enriches_actor_when_graph_enabled() -> None:
    activity = DummyActivity(text="Show my tasks")

    payload = await build_turn_payload(activity, search_users=_single_user_search, tool_profile="full")
    data = json.loads(serialize_turn_payload(payload))

    assert data["capabilities"]["graph_enabled"] is True
    assert data["actor"]["department"] == "IT"
    assert data["actor"]["department_code"] == "IT"
    assert data["actor"]["mail"] == "requester@example.com"


@pytest.mark.asyncio
async def test_build_turn_payload_groq_profile() -> None:
    activity = DummyActivity(text="List my tasks")

    payload = await build_turn_payload(activity, search_users=None, tool_profile="groq_chat")
    data = json.loads(serialize_turn_payload(payload))

    assert data["capabilities"]["tool_profile"] == "groq_chat"
