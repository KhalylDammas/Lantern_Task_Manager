from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from ltm.cards.builders import (
    assignee_disambiguation_card,
    draft_confirm_card,
    manager_verification_card,
    task_assignment_card,
    task_reopened_card,
)
from ltm.bot.mentions import MentionResolution, normalize_activity_text
from ltm.domain.enums import Priority
from ltm.domain.enums import DeptCode
from ltm.domain.models import TaskCreateDraft, UserRef
from ltm.bot.drafts import peek_draft, stash_draft, take_draft_in_session
from ltm.bot.context import set_interaction_revision, set_turn_context
from ltm.bot.tools import acknowledge_task_handler
from ltm.domain.models import AcknowledgeTaskParams
from ltm.bot.pending_mentions import stash_pending_disambiguation, take_pending_disambiguation
from ltm.interaction.coordinator import ResponseCoordinator
from ltm.interaction.models import InteractionOperation
from ltm.interaction.normalization import (
    clarification_assignee_query,
    derive_task_title,
    normalize_priority,
    parse_due_date,
    refers_to_self,
)
from ltm.interaction.store import InteractionStore


def _contains_input(value: object) -> bool:
    if isinstance(value, dict):
        return any(str(item).startswith("Input.") for item in [value.get("type")]) or any(
            _contains_input(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_input(item) for item in value)
    return False


def test_priority_aliases_default_and_title_derivation() -> None:
    assert normalize_priority("NORMAL") == Priority.MEDIUM
    assert normalize_priority("asap") == Priority.HIGH
    assert normalize_priority("blocking") == Priority.CRITICAL
    assert normalize_priority("not urgent") == Priority.LOW
    assert normalize_priority(None) == Priority.MEDIUM
    assert normalize_priority("invented") == Priority.MEDIUM
    assert derive_task_title("Review the invoice. Then notify finance.") == "Review the invoice"


def test_riyadh_dates_self_reference_and_unicode_task_id() -> None:
    base = datetime.fromisoformat("2026-07-21T10:00:00+03:00")
    assert parse_due_date("tomorrow", now=base).isoformat() == "2026-07-22"
    assert parse_due_date("31/07/2026", now=base).isoformat() == "2026-07-31"
    assert parse_due_date("no date here", now=base) is None
    assert refers_to_self("myself")
    assert normalize_activity_text("close LTM‑IT‑2026‑0001") == "close LTM-IT-2026-0001"
    assert clarification_assignee_query("Ahmed, tomorrow") == "Ahmed"
    assert clarification_assignee_query("Fatima next Thursday") == "Fatima"
    assert clarification_assignee_query("assign it to @Ahmed tomorrow") == "Ahmed"


def test_all_interaction_cards_are_action_only() -> None:
    candidate = MentionResolution(token="@Alex", user=UserRef(entra_object_id="alex", display_name="Alex"))
    cards = [
        draft_confirm_card(draft_id="d1", task_type="Review", assignee="Alex", due="2026-08-01",
                           priority="Medium", description="Review"),
        assignee_disambiguation_card(pick_id="p1", token="@Alex", query="Alex", candidates=(candidate,)),
        manager_verification_card(task_id="LTM-IT-2026-0001", summary="Done"),
        task_assignment_card(task_id="LTM-IT-2026-0001", task_type="Review", description="Review",
                             due="2026-08-01", priority="Medium", created_by_name="Alex"),
        task_reopened_card(task_id="LTM-IT-2026-0001", reason="Needs evidence"),
    ]
    for card in cards:
        payload = card.model_dump(by_alias=True, exclude_none=True)
        assert not _contains_input(payload)
        for action in payload.get("actions", []):
            assert action.get("data", {}).get("action_token")


def test_pending_interaction_is_durable_and_revisioned() -> None:
    store = InteractionStore()
    revision = store.begin_event(actor_id="actor", conversation_id="conversation", activity_id="a1")
    store.set_pending(actor_id="actor", conversation_id="conversation",
                      operation=InteractionOperation.CLOSE_TASK, slots={"x": 1},
                      missing_fields=["completion notes"], reference_id="LTM-IT-2026-0001")
    pending = InteractionStore().get(actor_id="actor", conversation_id="conversation")
    assert pending is not None
    assert pending.revision == revision
    assert pending.operation == InteractionOperation.CLOSE_TASK
    assert pending.reference_id == "LTM-IT-2026-0001"
    assert store.is_current(actor_id="actor", conversation_id="conversation", revision=revision)
    store.begin_event(actor_id="actor", conversation_id="conversation", activity_id="a2")
    assert not store.is_current(actor_id="actor", conversation_id="conversation", revision=revision)


def test_stale_pending_write_cannot_replace_newer_interaction() -> None:
    store = InteractionStore()
    stale_revision = store.begin_event(actor_id="actor", conversation_id="conversation", activity_id="old")
    current_revision = store.begin_event(actor_id="actor", conversation_id="conversation", activity_id="new")
    assert current_revision > stale_revision
    stored = store.set_pending(
        actor_id="actor", conversation_id="conversation",
        operation=InteractionOperation.REVIEW_DRAFT, slots={}, missing_fields=[],
        reference_id="stale-draft", expected_revision=stale_revision)
    assert stored is None
    current = store.get(actor_id="actor", conversation_id="conversation")
    assert current is not None and current.reference_id == ""


def test_card_receipt_is_stable_across_duplicate_invoke_activity_ids() -> None:
    coordinator = ResponseCoordinator()
    first = coordinator.action_key(action_token="card-token", activity_id="invoke-1",
                                   actor_id="actor", verb="draft.confirm", reference_id="draft")
    second = coordinator.action_key(action_token="card-token", activity_id="invoke-2",
                                    actor_id="actor", verb="draft.confirm", reference_id="draft")
    assert first == second
    assert coordinator.claim(first) == (True, None)
    coordinator.complete(first, code="TASK_CREATED", text="Task created")
    claimed, stored = coordinator.claim(second)
    assert not claimed
    assert stored is not None and stored.code == "TASK_CREATED" and stored.text == "Task created"


def test_disambiguation_survives_outside_process_memory() -> None:
    store = InteractionStore()
    revision = store.begin_event(actor_id="actor", conversation_id="conversation", activity_id="message")
    candidate = MentionResolution(
        token="@Alex",
        user=UserRef(entra_object_id="alex", display_name="Alex", department="IT"),
        mail="alex@example.com",
    )
    pick_id = stash_pending_disambiguation(
        actor_id="actor", conversation_id="conversation", token="@Alex", query="Alex",
        candidates=(candidate,), source="message", original_message="Create a task for @Alex",
        expected_revision=revision)
    restored = take_pending_disambiguation(
        pick_id, actor_id="actor", conversation_id="conversation")
    assert restored is not None
    assert restored.candidates[0].user.entra_object_id == "alex"
    assert restored.original_message == "Create a task for @Alex"


def test_draft_claim_rolls_back_with_task_transaction() -> None:
    draft = TaskCreateDraft(
        task_type="Review", description="Review safely", assignee_entra_id="actor",
        assignee_display_name="Actor", assignee_department="IT",
        assignee_department_code=DeptCode.IT, priority=Priority.MEDIUM,
        due_date=date.today() + timedelta(days=1))
    draft_id = stash_draft(draft, "actor")
    from ltm.storage.db import session_scope

    with pytest.raises(RuntimeError):
        with session_scope() as session:
            assert take_draft_in_session(session, draft_id, "actor") is not None
            raise RuntimeError("simulate task insert failure")
    assert peek_draft(draft_id, "actor") is not None


def test_interaction_coordinator_flag_is_a_real_kill_switch(monkeypatch) -> None:
    from ltm.config.settings import clear_settings_cache

    monkeypatch.setenv("LTM_INTERACTION_COORDINATOR_ENABLED", "false")
    clear_settings_cache()
    store = InteractionStore()
    assert store.begin_event(actor_id="actor", conversation_id="conversation") == 0
    assert store.set_pending(
        actor_id="actor", conversation_id="conversation",
        operation=InteractionOperation.CREATE_TASK, slots={}, missing_fields=["assignee"]
    ) is None
    assert store.get(actor_id="actor", conversation_id="conversation") is None


@pytest.mark.asyncio
async def test_stale_model_tool_cannot_transition_task(monkeypatch) -> None:
    actor = UserRef(entra_object_id="actor")
    set_turn_context(conversation_id="conversation", actor=actor)
    store = InteractionStore()
    stale_revision = store.begin_event(actor_id="actor", conversation_id="conversation", activity_id="old")
    set_interaction_revision(stale_revision)
    store.begin_event(actor_id="actor", conversation_id="conversation", activity_id="new")

    def unexpected_transition(*args, **kwargs):
        raise AssertionError("stale tool reached the lifecycle use case")

    monkeypatch.setattr("ltm.application.tasks.TaskUseCases.acknowledge", unexpected_transition)
    result = await acknowledge_task_handler(AcknowledgeTaskParams(task_id="LTM-IT-2026-0001"))
    assert "STALE_INTERACTION" in result
