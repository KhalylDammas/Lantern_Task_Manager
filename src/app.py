"""Lantern Task Manager — Microsoft Teams host entry (Microsoft 365 Agents Toolkit)."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, cast

from microsoft_teams.ai import AIModel, ChatPrompt, Function, ListMemory
from microsoft_teams.api import (
    AdaptiveCardInvokeActivity,
    InvokeResponse,
    MessageActivity,
    MessageActivityInput,
    MessageSubmitActionInvokeActivity,
)
from microsoft_teams.api.models.adaptive_card.adaptive_card_action_response import AdaptiveCardActionMessageResponse
from microsoft_teams.apps import ActivityContext
from microsoft_teams.cards import AdaptiveCard

from ltm.auth.tokens import auth_mode, graph_configured
from ltm.ai.memory_trim import trim_conversation_memory
from ltm.ai.model_factory import build_ai_model
from ltm.ai.redaction import redact
from ltm.ai.turn_payload import ActorContext, build_turn_payload, enrich_actor, serialize_turn_payload
from ltm.ai.tool_selection import select_tools_for_message
from ltm.bot.commands import fetch_task_list, format_task_list_message, match_list_filter
from ltm.bot.app_factory import create_teams_app
from ltm.bot.card_actions import dispatch_card_action
from ltm.cards.builders import (
    assignee_disambiguation_card,
    draft_confirm_card,
    task_assignment_card,
    task_created_card,
    task_detail_card,
)
from ltm.bot.context import (
    drain_pending_cards,
    get_interaction_revision,
    set_interaction_revision,
    set_turn_context,
)
from ltm.bot.help_text import help_message_text
from ltm.bot.drafts import discard_draft, peek_draft, stash_draft
from ltm.bot.http_routes import attach_http_routes
from ltm.bot.mentions import (
    AmbiguousMentionResolution,
    MentionResolution,
    normalize_activity_text,
    resolve_assignee_name,
    resolve_mentions_structured,
)
from ltm.bot.pending_mentions import (
    clear_mention_overrides,
    get_mention_overrides,
    set_mention_override,
    stash_pending_disambiguation,
    take_pending_disambiguation,
)
from ltm.bot.tools import CreateTaskToolParams, build_functions, build_functions_for_groq_chat, create_task_handler
from ltm.bot.startup import log_startup_probes
from ltm.config import initialize_settings
from ltm.config.settings import get_settings
from ltm.domain.models import CloseTaskParams, UserRef
from ltm.application import TaskUseCases
from ltm.interaction.models import InteractionOperation, InteractionOrigin
from ltm.interaction.store import InteractionStore
from ltm.interaction.coordinator import ResponseCoordinator
from ltm.interaction.normalization import (
    clarification_assignee_query,
    extract_priority,
    parse_due_date,
    refers_to_self,
)
from ltm.policy.profiles import department_label, get_profile
from ltm.graph.client import GraphClient
from ltm.notifications.service import NotificationService
from ltm.storage.conversation_bindings import ConversationBindingRepository
from ltm.storage.db import session_scope

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

settings = initialize_settings()
BOT_SEND_TIMEOUT_SECONDS = float(os.environ.get("BOT_SEND_TIMEOUT_SECONDS", "20"))
BOT_HTTP_TIMEOUT_SECONDS = float(os.environ.get("BOT_HTTP_TIMEOUT_SECONDS", "10"))

_INSTRUCTIONS_PATH = Path(__file__).resolve().parent / "ltm" / "ai" / "instructions.txt"


def load_instructions() -> str:
    try:
        return _INSTRUCTIONS_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "You are Lantern Task Manager (LTM)."


INSTRUCTIONS = load_instructions()


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def text_preview(value: str | None, *, limit: int = 180) -> str:
    preview = redact((value or "").replace("\n", " ").strip())
    if len(preview) <= limit:
        return preview
    return preview[: limit - 3] + "..."


app = create_teams_app(
    settings,
    skip_auth=env_flag("BOT_SKIP_AUTH"),
    http_timeout=BOT_HTTP_TIMEOUT_SECONDS,
)

_ai_model_singleton: AIModel | None = None


def ai_model() -> AIModel:
    global _ai_model_singleton
    if _ai_model_singleton is None:
        _ai_model_singleton = build_ai_model(get_settings())
    return _ai_model_singleton


def chat_tool_functions() -> list[Function[Any]]:
    profile = get_settings().llm_tool_profile
    if profile == "full":
        return build_functions()
    return build_functions_for_groq_chat()


conversation_store: dict[str, ListMemory] = {}
_turns_before_card: dict[str, int] = {}


def get_or_create_memory(conversation_id: str) -> ListMemory:
    conversation_store.setdefault(conversation_id, ListMemory())
    return conversation_store[conversation_id]


def sender_user_ref(activity: Any) -> UserRef:
    s = activity.from_
    oid = getattr(s, "aad_object_id", None) or s.id
    return UserRef(entra_object_id=str(oid), display_name=str(s.name or ""), department="")


def _increment_turns_before_card(conversation_id: str) -> None:
    _turns_before_card[conversation_id] = _turns_before_card.get(conversation_id, 0) + 1


def _log_turns_before_card(conversation_id: str, *, event: str) -> None:
    count = _turns_before_card.pop(conversation_id, 0)
    logger.info(
        "turns_before_card: conversation_id=%s count=%s event=%s",
        conversation_id,
        count,
        event,
    )


async def _send_disambiguation_intercept(
    ctx: ActivityContext[Any],
    ambiguity: AmbiguousMentionResolution,
    *,
    original_message: str,
) -> None:
    pick_id = stash_pending_disambiguation(
        conversation_id=ctx.activity.conversation.id,
        token=ambiguity.token,
        query=ambiguity.query,
        candidates=ambiguity.candidates,
        source="message",
        original_message=original_message,
        actor_id=sender_user_ref(ctx.activity).entra_object_id,
        expected_revision=get_interaction_revision(),
    )
    if not pick_id:
        return
    card = assignee_disambiguation_card(
        pick_id=pick_id,
        token=ambiguity.token,
        query=ambiguity.query,
        candidates=ambiguity.candidates,
        source="message",
    )
    await send_with_timeout(ctx, MessageActivityInput().add_card(card), label="assignee disambiguation card")
    await send_with_timeout(
        ctx,
        MessageActivityInput(text="Multiple people matched that name. Choose the correct assignee above to continue."),
        label="disambiguation prompt",
    )


async def run_ai_turn(
    ctx: ActivityContext[MessageActivity],
    *,
    memory: ListMemory,
    graph_search: Any,
    mention_overrides: dict[str, MentionResolution] | None = None,
    actor: ActorContext | None = None,
    mention_result: Any | None = None,
    interaction_revision: int | None = None,
) -> None:
    model = ai_model()
    settings = get_settings()
    tool_profile = settings.llm_tool_profile
    turn_payload = await build_turn_payload(
        ctx.activity,
        search_users=graph_search,
        tool_profile=tool_profile,
        mention_overrides=mention_overrides,
        mention_result=mention_result,
        actor=actor,
    )
    llm_input = serialize_turn_payload(turn_payload)
    available_tools = chat_tool_functions()
    selected_tools = (
        select_tools_for_message(available_tools, turn_payload.message)
        if settings.llm_dynamic_tools_enabled
        else available_tools
    )
    chat_prompt = ChatPrompt(model, functions=selected_tools)
    removed_messages = await trim_conversation_memory(
        memory,
        max_turns=settings.llm_memory_max_turns,
        max_tool_result_chars=settings.llm_memory_max_tool_result_chars,
        max_chars=settings.llm_memory_max_chars,
    )
    logger.info(
        "Sending message to AI model: activity_id=%s conversation_id=%s model=%s "
        "schema_version=%s actor_entra_id=%s enrichments=%s input_length=%s "
        "memory_trimmed_messages=%s available_tools=%s selected_tools=%s message_preview=%r",
        ctx.activity.id,
        ctx.activity.conversation.id,
        model.__class__.__name__,
        turn_payload.schema_version,
        turn_payload.actor.entra_object_id,
        turn_payload.enrichments is not None,
        len(llm_input),
        removed_messages,
        len(available_tools),
        [tool.name for tool in selected_tools],
        text_preview(turn_payload.message),
    )

    try:
        chat_result = await chat_prompt.send(
            input=llm_input,
            memory=memory,
            instructions=INSTRUCTIONS,
            on_chunk=lambda chunk: ctx.stream.emit(chunk),
        )
    except Exception:
        logger.exception("ChatPrompt failed")
        await send_with_timeout(
            ctx,
            MessageActivityInput(
                text="The assistant path failed. Please describe the task again in one message.",
            ),
            label="assistant failure response",
        )
        return

    outgoing = chat_result.response.content or ""
    pending_cards = drain_pending_cards()
    if interaction_revision is not None and not InteractionStore().is_current(
        actor_id=turn_payload.actor.entra_object_id,
        conversation_id=ctx.activity.conversation.id,
        revision=interaction_revision,
    ):
        logger.info("Discarding stale model response: activity_id=%s revision=%s",
                    ctx.activity.id, interaction_revision)
        return
    logger.info(
        "AI model response received: activity_id=%s outgoing_length=%s pending_cards=%s",
        ctx.activity.id,
        len(outgoing),
        len(pending_cards),
    )

    if pending_cards:
        _log_turns_before_card(ctx.activity.conversation.id, event="confirm_card")

    for card in pending_cards:
        await send_with_timeout(ctx, MessageActivityInput().add_card(card), label="pending card")

    if ctx.activity.conversation.is_group:
        if outgoing:
            await send_with_timeout(
                ctx,
                MessageActivityInput(text=outgoing).add_ai_generated().add_feedback(),
                label="group chat response",
            )
    else:
        if outgoing:
            await send_with_timeout(
                ctx,
                MessageActivityInput(text=outgoing).add_ai_generated().add_feedback(),
                label="personal chat response",
            )


async def send_with_timeout(ctx: ActivityContext[Any], message: Any, *, label: str) -> Any:
    logger.info("Sending %s: activity_id=%s timeout=%ss", label, ctx.activity.id, BOT_SEND_TIMEOUT_SECONDS)
    try:
        result = await asyncio.wait_for(ctx.send(message), timeout=BOT_SEND_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.exception("Timed out sending %s: activity_id=%s", label, ctx.activity.id)
        raise
    except Exception:
        logger.exception("Failed sending %s: activity_id=%s", label, ctx.activity.id)
        raise
    logger.info("Sent %s: activity_id=%s", label, ctx.activity.id)
    return result


def _persist_personal_conversation_binding(ctx: ActivityContext[Any]) -> None:
    """Cache Bot Framework ConversationReference for proactive sends (personal scope only)."""
    act = ctx.activity
    if getattr(act.conversation, "conversation_type", None) != "personal":
        return
    uid = sender_user_ref(act).entra_object_id
    if not uid:
        return
    try:
        with session_scope() as session:
            ConversationBindingRepository(session).upsert(uid, ctx.conversation_ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to persist conversation binding for user %s (store unavailable): %s",
            uid,
            exc,
        )


async def handle_stateful_conversation(ctx: ActivityContext[MessageActivity]) -> None:
    raw_entities = getattr(ctx.activity, "entities", None) or []
    logger.info(
        "Stateful conversation start: activity_id=%s conversation_id=%s conversation_type=%s "
        "is_group=%s from_id=%s from_aad=%s raw_text=%r entities=%s",
        ctx.activity.id,
        ctx.activity.conversation.id,
        getattr(ctx.activity.conversation, "conversation_type", None),
        getattr(ctx.activity.conversation, "is_group", None),
        getattr(ctx.activity.from_, "id", None),
        getattr(ctx.activity.from_, "aad_object_id", None),
        text_preview(ctx.activity.text),
        len(raw_entities),
    )
    memory = get_or_create_memory(ctx.activity.conversation.id)
    logger.info("Conversation memory ready: activity_id=%s", ctx.activity.id)

    set_turn_context(conversation_id=ctx.activity.conversation.id, actor=sender_user_ref(ctx.activity))
    logger.info("Turn context set: activity_id=%s", ctx.activity.id)

    _persist_personal_conversation_binding(ctx)
    logger.info("Conversation binding persistence step completed: activity_id=%s", ctx.activity.id)

    settings = get_settings()
    logger.info(
        "Settings loaded for inbound message: activity_id=%s graph_auth_mode=%s",
        ctx.activity.id,
        auth_mode(settings),
    )

    graph_search = None
    if graph_configured(settings):
        async def graph_search(query: str) -> list[dict[str, Any]]:
            logger.info(
                "Graph user search requested by mention resolver: activity_id=%s query=%r",
                ctx.activity.id,
                text_preview(query),
            )
            return await GraphClient(settings).search_users(query)

    text = normalize_activity_text(getattr(ctx.activity, "text", "") or "")
    logger.info(
        "Normalized inbound message text: activity_id=%s length=%s preview=%r graph_search_enabled=%s",
        ctx.activity.id,
        len(text),
        text_preview(text),
        graph_search is not None,
    )
    lowered = text.lower()
    actor_ref = sender_user_ref(ctx.activity)
    interaction_store = InteractionStore()
    interaction_revision = interaction_store.begin_event(
        actor_id=actor_ref.entra_object_id,
        conversation_id=ctx.activity.conversation.id,
        activity_id=ctx.activity.id or "")
    set_interaction_revision(interaction_revision)

    if lowered in {"cancel", "never mind", "nevermind", "/cancel"}:
        cancelled = interaction_store.get(actor_id=actor_ref.entra_object_id,
                                          conversation_id=ctx.activity.conversation.id)
        if cancelled and cancelled.operation == InteractionOperation.REVIEW_DRAFT and cancelled.reference_id:
            discard_draft(cancelled.reference_id, actor_ref.entra_object_id)
        interaction_store.clear(actor_id=actor_ref.entra_object_id,
                                conversation_id=ctx.activity.conversation.id)
        await send_with_timeout(ctx, MessageActivityInput(text="Cancelled."), label="cancel response")
        return

    pending = interaction_store.get(actor_id=actor_ref.entra_object_id,
                                    conversation_id=ctx.activity.conversation.id)
    explicit_new_command = (
        lowered.startswith(("/", "create ", "new task", "show ", "list ", "close ",
                            "reopen ", "acknowledge ", "resume ", "verify "))
        or lowered in {"help", "form", "manual task", "create task form"}
    )
    if pending and pending.operation and explicit_new_command:
        if pending.operation == InteractionOperation.REVIEW_DRAFT and pending.reference_id:
            discard_draft(pending.reference_id, actor_ref.entra_object_id)
        interaction_store.clear(actor_id=actor_ref.entra_object_id,
                                conversation_id=ctx.activity.conversation.id)
        pending = None
    if pending and pending.operation in {InteractionOperation.CLOSE_TASK, InteractionOperation.REOPEN_TASK}:
        origin = InteractionOrigin(actor_entra_id=actor_ref.entra_object_id,
                                   conversation_id=ctx.activity.conversation.id,
                                   conversation_type=getattr(ctx.activity.conversation, "conversation_type", "") or "",
                                   activity_id=ctx.activity.id or "", source="message")
        interaction_store.clear(actor_id=actor_ref.entra_object_id,
                                conversation_id=ctx.activity.conversation.id)
        if pending.operation == InteractionOperation.CLOSE_TASK:
            result = await TaskUseCases().close(
                CloseTaskParams(task_id=pending.reference_id, completion_notes=text), actor_ref, origin)
        else:
            result = await TaskUseCases().reopen(pending.reference_id, text, actor_ref)
        await send_with_timeout(ctx, MessageActivityInput(text=result.message), label="pending operation result")
        return

    if pending and pending.operation == InteractionOperation.CREATE_TASK:
        slots = dict(pending.slots)
        if slots.get("disambiguation"):
            await send_with_timeout(
                ctx,
                MessageActivityInput(text="Please choose the assignee from the card, or cancel this request."),
                label="disambiguation reminder",
            )
            return
        if "due date" in pending.missing_fields:
            due = parse_due_date(text)
            if due is not None:
                slots["due_date"] = due.isoformat()
        if "assignee" in pending.missing_fields and refers_to_self(text):
            slots["assignee_entra_id"] = actor_ref.entra_object_id
            slots["assignee"] = "me"
        elif "assignee" in pending.missing_fields and graph_search is not None:
            enriched_actor = await enrich_actor(actor_ref, graph_search)
            mention_resolution = await resolve_mentions_structured(
                ctx.activity,
                search_users=graph_search,
                requester=enriched_actor,
            )
            resolved = mention_resolution.resolved[0] if mention_resolution.resolved else None
            if resolved is None:
                assignee_query = clarification_assignee_query(text)
                pick = await resolve_assignee_name(
                    assignee_query,
                    graph_search,
                    requester=enriched_actor,
                ) if assignee_query else None
                resolved = pick.resolved if pick is not None else None
            if resolved is not None:
                slots["assignee_entra_id"] = resolved.user.entra_object_id
                slots["assignee_display_name"] = resolved.user.display_name
        missing = []
        if not slots.get("assignee_entra_id"):
            missing.append("assignee")
        if parse_due_date(slots.get("due_date")) is None:
            missing.append("due date")
        if not missing:
            interaction_store.clear(actor_id=actor_ref.entra_object_id,
                                    conversation_id=ctx.activity.conversation.id)
            result_text = await create_task_handler(CreateTaskToolParams.model_validate(slots))
            cards = drain_pending_cards()
            if cards:
                await send_with_timeout(ctx, MessageActivityInput().add_card(cards[-1]), label="completed draft card")
            elif result_text:
                await send_with_timeout(ctx, MessageActivityInput(text=result_text), label="completed draft response")
            return
        stored = interaction_store.set_pending(
            actor_id=actor_ref.entra_object_id,
            conversation_id=ctx.activity.conversation.id,
            operation=InteractionOperation.CREATE_TASK, slots=slots,
            missing_fields=missing, expected_revision=interaction_revision)
        if stored is None and interaction_store.enabled():
            return
        await send_with_timeout(
            ctx, MessageActivityInput(text=f"I still need {' and '.join(missing)}. Please provide them in one reply."),
            label="consolidated clarification")
        return

    if pending and pending.operation == InteractionOperation.REVIEW_DRAFT:
        draft = peek_draft(pending.reference_id, actor_ref.entra_object_id)
        if draft is None:
            interaction_store.clear(actor_id=actor_ref.entra_object_id,
                                    conversation_id=ctx.activity.conversation.id)
        else:
            updates: dict[str, Any] = {}
            priority = extract_priority(text)
            if priority is not None:
                updates["priority"] = priority
            due = parse_due_date(text)
            if due is not None:
                updates["due_date"] = due
            if refers_to_self(text) or "assign to me" in lowered:
                profile = get_profile(actor_ref.entra_object_id)
                updates.update(assignee_entra_id=actor_ref.entra_object_id,
                               assignee_display_name=profile.display_name or actor_ref.display_name,
                               assignee_department=department_label(profile.department_code),
                               assignee_department_code=profile.department_code)
            if lowered.startswith("description:"):
                updates["description"] = text.split(":", 1)[1].strip()
            if lowered.startswith(("title:", "type:")):
                updates["task_type"] = text.split(":", 1)[1].strip()[:200]
            if updates:
                revised = draft.model_copy(update=updates)
                draft_id = stash_draft(revised, actor_ref.entra_object_id)
                stored = interaction_store.set_pending(
                    actor_id=actor_ref.entra_object_id,
                    conversation_id=ctx.activity.conversation.id,
                    operation=InteractionOperation.REVIEW_DRAFT, slots={},
                    missing_fields=[], reference_id=draft_id,
                    expected_revision=interaction_revision)
                if stored is None and interaction_store.enabled():
                    discard_draft(draft_id, actor_ref.entra_object_id)
                    return
                discard_draft(pending.reference_id, actor_ref.entra_object_id)
                card = draft_confirm_card(
                    draft_id=draft_id, task_type=revised.task_type,
                    assignee=revised.assignee_display_name or revised.assignee_entra_id,
                    due=str(revised.due_date), priority=str(revised.priority),
                    description=revised.description,
                    assignee_department=revised.assignee_department)
                await send_with_timeout(ctx, MessageActivityInput().add_card(card), label="revised draft card")
                return

    if lowered in {"/help", "help"}:
        logger.info("Handling help command: activity_id=%s", ctx.activity.id)
        await send_with_timeout(
            ctx,
            MessageActivityInput(text=help_message_text(graph_enabled=graph_search is not None)),
            label="help response",
        )
        return

    list_filter = match_list_filter(lowered)
    if list_filter:
        logger.info("Handling list command: activity_id=%s filter=%s", ctx.activity.id, list_filter)
        actor_ref = sender_user_ref(ctx.activity)
        actor = await enrich_actor(actor_ref, graph_search)
        try:
            tasks = await asyncio.to_thread(
                fetch_task_list,
                viewer_entra_id=actor.entra_object_id,
                filter_name=list_filter,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to fetch task list for activity_id=%s filter=%s (store unavailable): %s",
                ctx.activity.id,
                list_filter,
                exc,
            )
            await send_with_timeout(
                ctx,
                MessageActivityInput(
                    text=(
                        "I'm having trouble loading tasks from the database right now. "
                        "Please try again in a few minutes."
                    )
                ),
                label=f"{list_filter} unavailable",
            )
            return
        msg = format_task_list_message(tasks=tasks, variant=list_filter)
        await send_with_timeout(ctx, MessageActivityInput(text=msg), label=f"{list_filter} response")
        return

    if lowered in {"/form", "form", "manual task", "create task form"}:
        logger.info("Handling form command: activity_id=%s", ctx.activity.id)
        await send_with_timeout(
            ctx,
            MessageActivityInput(text="Describe the task naturally, including who it is for and when it is due."),
            label="form guidance",
        )
        return

    if lowered.startswith("/who ") and graph_configured(get_settings()):
        logger.info("Handling /who command: activity_id=%s query=%r", ctx.activity.id, text_preview(text[5:]))
        graph = GraphClient(get_settings())
        q = text[5:].strip()
        people = await graph.search_users(q) if q else []
        lines = [
            f"{p['display_name']} — `{p['entra_object_id']}` ({p.get('department','')})" for p in people
        ]
        msg = "\n".join(lines) if lines else "No results (check Graph app permissions and query)."
        logger.info("Prepared /who response: activity_id=%s results=%s", ctx.activity.id, len(people))
        await send_with_timeout(ctx, MessageActivityInput(text=msg), label="/who response")
        return

    _increment_turns_before_card(ctx.activity.conversation.id)
    overrides = get_mention_overrides(ctx.activity.conversation.id)
    actor = await enrich_actor(actor_ref, graph_search)
    mention_result = await resolve_mentions_structured(
        ctx.activity,
        search_users=graph_search,
        requester=actor,
        mention_overrides=overrides,
    )
    if mention_result.ambiguous:
        await _send_disambiguation_intercept(
            ctx,
            mention_result.ambiguous[0],
            original_message=text,
        )
        return

    await run_ai_turn(
        ctx,
        memory=memory,
        graph_search=graph_search,
        mention_overrides=overrides,
        actor=actor,
        mention_result=mention_result,
        interaction_revision=interaction_revision,
    )

    logger.info("Stateful conversation completed: activity_id=%s", ctx.activity.id)


@app.on_message
async def handle_message(ctx: ActivityContext[MessageActivity]):
    logger.info(
        "on_message handler reached: activity_id=%s conversation_id=%s text=%r",
        ctx.activity.id,
        ctx.activity.conversation.id,
        text_preview(ctx.activity.text),
    )
    await handle_stateful_conversation(ctx)
    logger.info("on_message handler completed: activity_id=%s", ctx.activity.id)


@app.on_card_action
async def handle_card_action(
    ctx: ActivityContext[AdaptiveCardInvokeActivity],
) -> InvokeResponse[AdaptiveCardActionMessageResponse]:
    _persist_personal_conversation_binding(ctx)
    action = ctx.activity.value.action
    raw_data = action.data
    merged: dict[str, Any] = dict(raw_data) if isinstance(raw_data, dict) else {}
    # Action.Execute: verb on action; Action.Submit (legacy): verb may live only in data.
    verb = cast(str | None, action.verb or merged.get("verb"))
    uid = sender_user_ref(ctx.activity).entra_object_id
    ref_id = merged.get("draft_id") or merged.get("task_id")
    response_coordinator = ResponseCoordinator()
    receipt_key = response_coordinator.action_key(
        action_token=str(merged.get("action_token") or ""),
        activity_id=ctx.activity.id or "", actor_id=uid,
        verb=verb or "", reference_id=str(ref_id or ""))
    logger.info(
        "Card action received: activity_id=%s verb=%s ref=%s user=%s",
        ctx.activity.id,
        verb,
        ref_id,
        uid,
    )

    async def respond(
        msg: str,
        *,
        outcome: str = "ok",
        card: AdaptiveCard | None = None,
    ) -> InvokeResponse[AdaptiveCardActionMessageResponse]:
        """Return invoke body and mirror a short reply or card in-chat."""
        logger.info(
            "Card action outcome: activity_id=%s verb=%s ref=%s outcome=%s message=%r card=%s",
            ctx.activity.id,
            verb,
            ref_id,
            outcome,
            msg[:200],
            card is not None,
        )
        response_coordinator.complete(receipt_key, code=outcome, text=msg)
        try:
            if card is not None:
                await ctx.send(MessageActivityInput().add_card(card))
            elif msg:
                await ctx.send(msg)
        except Exception:  # noqa: BLE001
            logger.exception("Card action follow-up ctx.send failed")
        return InvokeResponse(status=200, body=AdaptiveCardActionMessageResponse(value=msg or "OK"))

    claimed, stored = response_coordinator.claim(receipt_key)
    if not claimed:
        assert stored is not None
        return InvokeResponse(status=200, body=AdaptiveCardActionMessageResponse(value=stored.text))

    interaction_store = InteractionStore()
    card_revision = interaction_store.begin_event(
        actor_id=uid, conversation_id=ctx.activity.conversation.id,
        activity_id=ctx.activity.id or "")
    set_interaction_revision(card_revision)
    if verb in {"task.close", "task.reject"} and ref_id:
        operation = (InteractionOperation.CLOSE_TASK if verb == "task.close"
                     else InteractionOperation.REOPEN_TASK)
        stored = interaction_store.set_pending(
            actor_id=uid, conversation_id=ctx.activity.conversation.id,
            operation=operation, slots={},
            missing_fields=["completion notes" if verb == "task.close" else "reason"],
            reference_id=str(ref_id), expected_revision=card_revision)
        if stored is None and interaction_store.enabled():
            return await respond("A newer interaction superseded this action.", outcome="stale_action")
        prompt = ("Tell me the completion notes in your next message."
                  if verb == "task.close" else "Tell me the reason for reopening in your next message.")
        return await respond(prompt, outcome="pending_details")

    dispatched = await dispatch_card_action(verb, merged, sender_user_ref(ctx.activity))
    if dispatched.handled:
        result = dispatched.result
        if result is None:
            return await respond("Card action failed.", outcome="dispatch_error")
        if result.code == "TASK_FOUND" and result.value is not None:
            task = result.value
            card = task_detail_card(
                task_id=task.id,
                task_type=task.task_type,
                status=str(task.status),
                due=str(task.due_date),
                priority=str(task.priority),
                assignee_name=task.assigned_to.display_name or task.assigned_to.entra_object_id,
                created_by_name=task.created_by.display_name or task.created_by.entra_object_id,
                description=task.description,
            )
            return await respond("", outcome="task_found", card=card)
        if result.code == "TASK_CREATED" and result.value is not None:
            interaction_store.clear(actor_id=uid, conversation_id=ctx.activity.conversation.id)
            task = result.value
            card = task_created_card(
                task_id=task.id, task_type=task.task_type, description=task.description,
                due=str(task.due_date), priority=str(task.priority),
                assignee_name=task.assigned_to.display_name or task.assigned_to.entra_object_id)
            return await respond(result.message, outcome="task_created", card=card)
        if result.code == "DRAFT_CANCELLED":
            interaction_store.clear(actor_id=uid, conversation_id=ctx.activity.conversation.id)
        return await respond(result.message, outcome=result.code.lower())

    if verb == "pick_assignee":
        pick_id = str(merged.get("pick_id") or "")
        selected_id = str(merged.get("assignee_entra_id") or "").strip()
        pending = take_pending_disambiguation(
            pick_id,
            actor_id=uid,
            conversation_id=ctx.activity.conversation.id,
        ) if pick_id else None
        if pending is None or not selected_id:
            return await respond("Selection expired or missing. Send your request again.", outcome="expired")

        selected = next(
            (candidate for candidate in pending.candidates if candidate.user.entra_object_id == selected_id),
            None,
        )
        if selected is None:
            return await respond("Invalid selection.", outcome="invalid_selection")

        set_mention_override(pending.conversation_id, pending.token, selected)

        set_turn_context(conversation_id=pending.conversation_id, actor=sender_user_ref(ctx.activity))
        set_interaction_revision(card_revision)
        memory = get_or_create_memory(pending.conversation_id)
        settings = get_settings()

        async def graph_search(query: str) -> list[dict[str, Any]]:
            return await GraphClient(settings).search_users(query)

        actor_ref = sender_user_ref(ctx.activity)
        actor = await enrich_actor(actor_ref, graph_search)
        overrides = get_mention_overrides(pending.conversation_id)

        class _ReplayActivity:
            def __init__(self) -> None:
                self.text = pending.original_message
                self.entities = getattr(ctx.activity, "entities", None) or []
                self.from_ = ctx.activity.from_
                self.conversation = ctx.activity.conversation
                self.id = ctx.activity.id

        replay = _ReplayActivity()
        mention_result = await resolve_mentions_structured(
            replay,
            search_users=graph_search,
            requester=actor,
            mention_overrides=overrides,
        )
        if mention_result.ambiguous:
            await _send_disambiguation_intercept(
                ctx,
                mention_result.ambiguous[0],
                original_message=pending.original_message,
            )
            return await respond("Another assignee still needs selection.", outcome="ambiguous")

        await run_ai_turn(
            ctx,
            memory=memory,
            graph_search=graph_search,
            mention_overrides=overrides,
            actor=actor,
            mention_result=mention_result,
            interaction_revision=card_revision,
        )
        clear_mention_overrides(pending.conversation_id)
        response_coordinator.complete(receipt_key, code="continued", text="Assignee selected.")
        return InvokeResponse(
            status=200,
            body=AdaptiveCardActionMessageResponse(value="Assignee selected."),
        )

    return await respond("Unknown card action.", outcome="unknown_verb")


@app.on_message_submit_feedback
async def handle_message_feedback(ctx: ActivityContext[MessageSubmitActionInvokeActivity]):
    logger.info("Teams feedback event received.")


@app.on_conversation_update
async def handle_conversation_update(ctx: ActivityContext[Any]) -> None:
    """Welcome + binding when user adds LTM in personal chat."""
    act = ctx.activity
    if getattr(act.conversation, "conversation_type", None) != "personal":
        return

    members_added = getattr(act, "members_added", None) or getattr(act, "membersAdded", None) or []
    if not members_added:
        return

    user = sender_user_ref(act)
    if not user.entra_object_id:
        return

    _persist_personal_conversation_binding(ctx)

    logger.info("Personal install/conversation update for user=%s", user.entra_object_id)
    try:
        with session_scope() as session:
            NotificationService(session, get_settings()).notify_welcome(
                user_entra_id=user.entra_object_id,
                user_display_name=user.display_name,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Welcome notification failed user=%s", user.entra_object_id)


_adapter_app = getattr(app.server.adapter, "app", None)
if _adapter_app is not None:
    attach_http_routes(_adapter_app, Path(__file__).resolve().parent / "static" / "legal")


if __name__ == "__main__":
    log_startup_probes()
    asyncio.run(app.start(settings.port))
