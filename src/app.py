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
from ltm.bot.commands import fetch_task_list, format_task_list_message, match_list_filter
from ltm.bot.app_factory import create_teams_app
from ltm.bot.card_actions import dispatch_card_action
from ltm.cards.builders import (
    assignee_disambiguation_card,
    draft_confirm_card,
    manual_task_form_card,
    task_detail_card,
)
from ltm.bot.context import drain_pending_cards, push_pending_card, set_turn_context
from ltm.bot.help_text import help_message_text
from ltm.bot.drafts import stash_draft
from ltm.bot.http_routes import attach_http_routes
from ltm.bot.mentions import (
    AmbiguousMentionResolution,
    MentionResolution,
    normalize_activity_text,
    resolve_assignee_name,
    resolve_mentions_structured,
)
from ltm.bot.pending_mentions import (
    build_manual_draft,
    clear_mention_overrides,
    get_mention_overrides,
    set_mention_override,
    stash_pending_disambiguation,
    take_pending_disambiguation,
)
from ltm.bot.tools import build_functions, build_functions_for_groq_chat
from ltm.bot.startup import log_startup_probes
from ltm.config import initialize_settings
from ltm.config.settings import get_settings
from ltm.domain.models import TaskCreateDraft, UserRef
from ltm.graph.client import GraphClient
from ltm.notifications.service import NotificationService
from ltm.policy import AssignmentPolicyError, assert_assignee_department_matches, assert_can_assign
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


def assignment_authorization_error(requester: UserRef, draft: TaskCreateDraft) -> str | None:
    """Return user-visible denial message, or None when assignment is allowed."""
    try:
        assert_assignee_department_matches(
            assignee_entra_id=draft.assignee_entra_id,
            assignee_department_code=draft.assignee_department_code,
        )
        assert_can_assign(
            requester_entra_id=requester.entra_object_id,
            assignee_entra_id=draft.assignee_entra_id,
        )
    except AssignmentPolicyError as exc:
        return exc.user_message
    return None


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


async def _send_confirm_draft_card(
    ctx: ActivityContext[Any],
    draft: TaskCreateDraft,
    *,
    assignee: MentionResolution | None = None,
) -> str | None:
    """Stash draft and send confirm card. Returns denial message or None on success."""

    requester = sender_user_ref(ctx.activity)
    denial = assignment_authorization_error(requester, draft)
    if denial:
        return denial

    draft_id = stash_draft(draft, requester.entra_object_id)
    card = draft_confirm_card(
        draft_id=draft_id,
        task_type=draft.task_type,
        assignee=f"{draft.assignee_display_name or draft.assignee_entra_id} ({draft.assignee_department_code.value})",
        due=str(draft.due_date),
        priority=str(draft.priority),
        description=draft.description,
        po=draft.d365.purchase_order_number,
        assignee_department=draft.assignee_department or draft.assignee_department_code.value,
        assignee_mail=assignee.mail if assignee else None,
        assignee_job_title=assignee.job_title if assignee else None,
    )
    await send_with_timeout(ctx, MessageActivityInput().add_card(card), label="confirm draft card")
    _log_turns_before_card(ctx.activity.conversation.id, event="confirm_card")
    return None


async def _send_disambiguation_intercept(
    ctx: ActivityContext[Any],
    ambiguity: AmbiguousMentionResolution,
    *,
    original_message: str,
    source: str = "message",
    manual_form_fields: dict[str, Any] | None = None,
) -> None:
    pick_id = stash_pending_disambiguation(
        conversation_id=ctx.activity.conversation.id,
        token=ambiguity.token,
        query=ambiguity.query,
        candidates=ambiguity.candidates,
        source=source,  # type: ignore[arg-type]
        original_message=original_message,
        manual_form_fields=manual_form_fields,
    )
    card = assignee_disambiguation_card(
        pick_id=pick_id,
        token=ambiguity.token,
        query=ambiguity.query,
        candidates=ambiguity.candidates,
        source=source,
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
) -> None:
    model = ai_model()
    settings = get_settings()
    chat_prompt = ChatPrompt(model, functions=chat_tool_functions())
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
    removed_messages = await trim_conversation_memory(
        memory,
        max_turns=settings.llm_memory_max_turns,
        max_tool_result_chars=settings.llm_memory_max_tool_result_chars,
    )
    logger.info(
        "Sending message to AI model: activity_id=%s conversation_id=%s model=%s "
        "schema_version=%s actor_entra_id=%s enrichments=%s input_length=%s "
        "memory_trimmed_messages=%s message_preview=%r",
        ctx.activity.id,
        ctx.activity.conversation.id,
        model.__class__.__name__,
        turn_payload.schema_version,
        turn_payload.actor.entra_object_id,
        turn_payload.enrichments is not None,
        len(llm_input),
        removed_messages,
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
                text=(
                    "The assistant path failed. Type form for structured capture — "
                    "you will still review a confirmation card before the task is created."
                ),
            ),
            label="assistant failure response",
        )
        await send_with_timeout(
            ctx,
            MessageActivityInput().add_card(manual_task_form_card()),
            label="fallback form",
        )
        return

    outgoing = chat_result.response.content or ""
    pending_cards = drain_pending_cards()
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
            MessageActivityInput().add_card(manual_task_form_card()),
            label="form card",
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
    actor_ref = sender_user_ref(ctx.activity)
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
            source="message",
        )
        return

    await run_ai_turn(
        ctx,
        memory=memory,
        graph_search=graph_search,
        mention_overrides=overrides,
        actor=actor,
        mention_result=mention_result,
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
        try:
            if card is not None:
                await ctx.send(MessageActivityInput().add_card(card))
            elif msg:
                await ctx.send(msg)
        except Exception:  # noqa: BLE001
            logger.exception("Card action follow-up ctx.send failed")
        return InvokeResponse(status=200, body=AdaptiveCardActionMessageResponse(value=msg or "OK"))

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
        return await respond(result.message, outcome=result.code.lower())

    if verb == "manual_create_submit":
        try:
            settings = get_settings()
            requester = sender_user_ref(ctx.activity)
            assignee_name = str(merged.get("assignee_name") or "").strip()
            if not assignee_name:
                return await respond("Assignee name is required.", outcome="validation_error")

            if not graph_configured(settings):
                return await respond(
                    "Directory search is unavailable. Configure Graph permissions or use natural language with @mentions.",
                    outcome="graph_unavailable",
                )

            async def graph_search(query: str) -> list[dict[str, Any]]:
                return await GraphClient(settings).search_users(query)

            actor = await enrich_actor(requester, graph_search)
            pick = await resolve_assignee_name(assignee_name, graph_search, requester=actor)
            form_fields = dict(merged)

            if pick.resolved is None:
                if not pick.ranked_candidates:
                    return await respond(
                        f"No directory matches for {assignee_name!r}. Check the name and try again.",
                        outcome="not_found",
                    )
                ambiguity = AmbiguousMentionResolution(
                    token=f"@{assignee_name}",
                    query=assignee_name,
                    candidates=pick.ranked_candidates,
                )
                await _send_disambiguation_intercept(
                    ctx,
                    ambiguity,
                    original_message="",
                    source="manual_form",
                    manual_form_fields=form_fields,
                )
                return await respond("Multiple matches found — choose the assignee above.", outcome="ambiguous")

            draft = build_manual_draft(form_fields, pick.resolved)
            denial = await _send_confirm_draft_card(ctx, draft, assignee=pick.resolved)
            if denial:
                return await respond(denial, outcome="denied")
            return await respond("Review and confirm the task card.", outcome="draft_prepared")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Manual create failed")
            return await respond(f"Validation error: {exc}", outcome="validation_error")

    if verb == "pick_assignee":
        pick_id = str(merged.get("pick_id") or "")
        selected_id = str(merged.get("assignee_entra_id") or "").strip()
        pending = take_pending_disambiguation(pick_id) if pick_id else None
        if pending is None or not selected_id:
            return await respond("Selection expired or missing. Send your request again.", outcome="expired")

        selected = next(
            (candidate for candidate in pending.candidates if candidate.user.entra_object_id == selected_id),
            None,
        )
        if selected is None:
            return await respond("Invalid selection.", outcome="invalid_selection")

        set_mention_override(pending.conversation_id, pending.token, selected)

        if pending.source == "manual_form":
            draft = build_manual_draft(pending.manual_form_fields, selected)
            denial = await _send_confirm_draft_card(ctx, draft, assignee=selected)
            if denial:
                return await respond(denial, outcome="denied")
            return await respond("Review and confirm the task card.", outcome="draft_prepared")

        set_turn_context(conversation_id=pending.conversation_id, actor=sender_user_ref(ctx.activity))
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
                source="message",
            )
            return await respond("Another assignee still needs selection.", outcome="ambiguous")

        await run_ai_turn(
            ctx,
            memory=memory,
            graph_search=graph_search,
            mention_overrides=overrides,
            actor=actor,
            mention_result=mention_result,
        )
        clear_mention_overrides(pending.conversation_id)
        return await respond("Continuing with your selected assignee.", outcome="continued")

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
