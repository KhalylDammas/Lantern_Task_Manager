from __future__ import annotations

import pytest
from microsoft_teams.api import Account, MentionEntity

from ltm.bot.mentions import resolve_mentions_in_text, resolve_mentions_structured


class DummyActivity:
    def __init__(self, text: str, entities: list[object] | None = None) -> None:
        self.text = text
        self.entities = entities


async def _single_user_search(query: str) -> list[dict[str, str]]:
    if query == "Alice Jones":
        return [
            {
                "entra_object_id": "entra-alice",
                "display_name": "Alice Jones",
                "department": "Finance",
                "mail": "alice@example.com",
                "job_title": "Controller",
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


async def _exact_user_search(query: str) -> list[dict[str, str]]:
    if query == "Alice Jones":
        return [
            {"entra_object_id": "entra-other", "display_name": "Alice Joneson", "department": "IT"},
            {"entra_object_id": "entra-alice", "display_name": "Alice Jones", "department": "Finance"},
        ]
    return []


async def _jabirs_user_search(query: str) -> list[dict[str, str]]:
    if query == "Jabirs":
        return [
            {
                "entra_object_id": "entra-jabirs",
                "display_name": "Jabirs",
                "department": "IT",
            }
        ]
    return []


@pytest.mark.asyncio
async def test_resolve_mentions_from_entities() -> None:
    activity = DummyActivity(
        text="<at>Alice Jones</at> please approve this task",
        entities=[
            MentionEntity(
                mentioned=Account(id="29:alice", aad_object_id="entra-alice", name="Alice Jones"),
                text="<at>Alice Jones</at>",
            )
        ],
    )

    result = await resolve_mentions_structured(activity)

    assert "@Alice Jones [EntraObjectId: entra-alice]" in result.message
    assert len(result.resolved) == 1
    assert result.resolved[0].user.entra_object_id == "entra-alice"
    assert result.ambiguous == ()


@pytest.mark.asyncio
async def test_resolve_entity_mentions_enriches_directory_details() -> None:
    activity = DummyActivity(
        text="<at>Alice Jones</at> please approve this task",
        entities=[
            MentionEntity(
                mentioned=Account(id="29:alice", aad_object_id="entra-alice", name="Alice Jones"),
                text="<at>Alice Jones</at>",
            )
        ],
    )

    result = await resolve_mentions_structured(activity, search_users=_single_user_search)

    assert result.resolved[0].user.entra_object_id == "entra-alice"
    assert result.resolved[0].user.display_name == "Alice Jones"
    assert result.resolved[0].user.department == "Finance"
    assert result.resolved[0].mail == "alice@example.com"
    assert result.resolved[0].job_title == "Controller"
    assert "Directory-resolved mentioned users:" not in result.message


@pytest.mark.asyncio
async def test_resolve_plaintext_mentions_with_unique_graph_match() -> None:
    activity = DummyActivity(text="@Alice Jones please approve this task")

    result = await resolve_mentions_structured(activity, search_users=_single_user_search)

    assert "@Alice Jones [EntraObjectId: entra-alice]" in result.message
    assert result.resolved[0].user.entra_object_id == "entra-alice"
    assert result.resolved[0].user.display_name == "Alice Jones"
    assert result.resolved[0].user.department == "Finance"


@pytest.mark.asyncio
async def test_plaintext_mentions_surface_ambiguous_graph_matches() -> None:
    activity = DummyActivity(text="@Alice please approve this task")

    result = await resolve_mentions_structured(activity, search_users=_ambiguous_user_search)

    assert result.message == "@Alice please approve this task"
    assert result.resolved == ()
    assert len(result.ambiguous) == 1
    assert result.ambiguous[0].token == "@Alice"
    assert len(result.ambiguous[0].candidates) == 2
    assert result.ambiguous[0].candidates[0].user.entra_object_id == "entra-1"


@pytest.mark.asyncio
async def test_plaintext_mentions_use_single_exact_match_when_search_returns_multiple() -> None:
    activity = DummyActivity(text="@Alice Jones please approve this task")

    result = await resolve_mentions_structured(activity, search_users=_exact_user_search)

    assert "@Alice Jones [EntraObjectId: entra-alice]" in result.message
    assert result.resolved[0].user.entra_object_id == "entra-alice"
    assert result.resolved[0].user.display_name == "Alice Jones"
    assert result.ambiguous == ()


@pytest.mark.asyncio
async def test_plaintext_mention_search_stops_before_assignment_connector() -> None:
    activity = DummyActivity(
        text=(
            "assign a task to @Jabirs to review the latest update on the project."
            "The task is due 18th of May 2026Priority: normalTask type:, updates review"
        )
    )
    queries: list[str] = []

    async def search_users(query: str) -> list[dict[str, str]]:
        queries.append(query)
        return await _jabirs_user_search(query)

    result = await resolve_mentions_structured(activity, search_users=search_users)

    assert queries == ["Jabirs"]
    assert "@Jabirs [EntraObjectId: entra-jabirs] to review" in result.message
    assert result.resolved[0].user.entra_object_id == "entra-jabirs"
    assert result.resolved[0].user.display_name == "Jabirs"
    assert result.resolved[0].user.department == "IT"


@pytest.mark.asyncio
async def test_plaintext_mention_search_strips_sentence_punctuation() -> None:
    activity = DummyActivity(
        text=(
            "I need you to assign a task to @abdulkhaliqa. "
            "The task is to review the recent response from our partners."
        )
    )
    queries: list[str] = []

    async def search_users(query: str) -> list[dict[str, str]]:
        queries.append(query)
        if query == "abdulkhaliqa":
            return [
                {
                    "entra_object_id": "entra-abdulkhaliq",
                    "display_name": "Abdulkhaliq Abdullah",
                    "department": "IT",
                    "mail": "abdulkhaliqa@lanternsystems.com",
                }
            ]
        return []

    result = await resolve_mentions_structured(activity, search_users=search_users)

    assert queries == ["abdulkhaliqa"]
    assert "@abdulkhaliqa [EntraObjectId: entra-abdulkhaliq]." in result.message
    assert result.resolved[0].user.entra_object_id == "entra-abdulkhaliq"
    assert result.resolved[0].user.display_name == "Abdulkhaliq Abdullah"


@pytest.mark.asyncio
async def test_legacy_resolve_mentions_in_text_still_includes_prose_blocks() -> None:
    activity = DummyActivity(text="@Alice Jones please approve this task")

    resolved = await resolve_mentions_in_text(activity, search_users=_single_user_search)

    assert "Directory-resolved mentioned users:" in resolved
    assert "assignee_entra_id: entra-alice" in resolved
