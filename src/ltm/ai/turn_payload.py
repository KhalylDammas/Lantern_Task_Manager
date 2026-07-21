"""Build JSON turn envelopes for LLM input (lifecycle-agnostic)."""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from ltm.ai.redaction import redact
from ltm.domain.business_time import business_now
from ltm.bot.mentions import (
    AmbiguousMentionResolution,
    MentionResolution,
    MentionResolutionResult,
    department_code,
    resolve_mentions_structured,
)
from ltm.domain.models import UserRef

TASK_ID_RE = re.compile(r"LTM-(?:FIN|PROC|OP|PROJ|HR|IT|BD|SAL|CEO)-\d{4}-\d{4}", re.IGNORECASE)
ToolProfile = Literal["full", "groq_chat"]


class TurnMeta(BaseModel):
    activity_id: str = ""
    timestamp: str = ""


class ActorContext(BaseModel):
    entra_object_id: str
    display_name: str = ""
    department: str = ""
    department_code: str = ""
    mail: str = ""
    user_principal_name: str = ""
    job_title: str = ""


class ConversationContext(BaseModel):
    id: str = ""
    type: str | None = None
    is_group: bool | None = None


class CapabilitiesContext(BaseModel):
    graph_enabled: bool = False
    tool_profile: ToolProfile = "full"


class ResolvedMentionEnrichment(BaseModel):
    token: str
    assignee_entra_id: str
    assignee_display_name: str = ""
    assignee_department: str = ""
    assignee_department_code: str = ""
    mail: str = ""
    user_principal_name: str = ""
    job_title: str = ""


class AmbiguousMentionCandidate(BaseModel):
    display_name: str = ""
    assignee_entra_id: str
    assignee_department: str = ""
    assignee_department_code: str = ""
    mail: str = ""
    user_principal_name: str = ""
    job_title: str = ""


class AmbiguousMentionEnrichment(BaseModel):
    token: str
    query: str
    candidates: list[AmbiguousMentionCandidate] = Field(default_factory=list)


class MentionEnrichments(BaseModel):
    resolved: list[ResolvedMentionEnrichment] = Field(default_factory=list)
    ambiguous: list[AmbiguousMentionEnrichment] = Field(default_factory=list)


class Enrichments(BaseModel):
    mentions: MentionEnrichments | None = None
    task_references: list[str] = Field(default_factory=list)


class TurnPayload(BaseModel):
    schema_version: Literal["1"] = "1"
    turn: TurnMeta
    actor: ActorContext
    conversation: ConversationContext
    capabilities: CapabilitiesContext
    message: str
    enrichments: Enrichments | None = None


def extract_task_references(message: str) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for match in TASK_ID_RE.finditer(message):
        task_id = match.group(0).upper()
        if task_id not in seen:
            seen.add(task_id)
            refs.append(task_id)
    return refs


def _resolved_mention_enrichment(mention: MentionResolution) -> ResolvedMentionEnrichment:
    user = mention.user
    return ResolvedMentionEnrichment(
        token=mention.token,
        assignee_entra_id=user.entra_object_id,
        assignee_display_name=user.display_name or mention.token[1:],
        assignee_department=user.department,
        assignee_department_code=department_code(user.department),
        mail=mention.mail,
        user_principal_name=mention.upn,
        job_title=mention.job_title,
    )


def _ambiguous_mention_enrichment(ambiguity: AmbiguousMentionResolution) -> AmbiguousMentionEnrichment:
    return AmbiguousMentionEnrichment(
        token=ambiguity.token,
        query=ambiguity.query,
        candidates=[
            AmbiguousMentionCandidate(
                display_name=candidate.user.display_name or candidate.token[1:],
                assignee_entra_id=candidate.user.entra_object_id,
                assignee_department=candidate.user.department,
                assignee_department_code=department_code(candidate.user.department),
                mail=candidate.mail,
                user_principal_name=candidate.upn,
                job_title=candidate.job_title,
            )
            for candidate in ambiguity.candidates
        ],
    )


def _mention_enrichments(result: MentionResolutionResult) -> MentionEnrichments | None:
    if not result.resolved and not result.ambiguous:
        return None
    return MentionEnrichments(
        resolved=[_resolved_mention_enrichment(m) for m in result.resolved],
        ambiguous=[_ambiguous_mention_enrichment(a) for a in result.ambiguous],
    )


def _build_enrichments(
    mention_result: MentionResolutionResult,
    message: str,
) -> Enrichments | None:
    mentions = _mention_enrichments(mention_result)
    task_refs = extract_task_references(message)
    if mentions is None and not task_refs:
        return None
    return Enrichments(
        mentions=mentions,
        task_references=task_refs,
    )


def actor_from_user_ref(user: UserRef) -> ActorContext:
    return ActorContext(
        entra_object_id=user.entra_object_id,
        display_name=user.display_name,
        department=user.department,
        department_code=department_code(user.department),
    )


async def enrich_actor(
    actor: UserRef,
    search_users: Callable[[str], Awaitable[list[dict[str, Any]]]] | None,
) -> ActorContext:
    base = actor_from_user_ref(actor)
    if search_users is None:
        return base

    query = actor.display_name.strip()
    if not query:
        return base

    candidates = await search_users(query)
    match = next(
        (c for c in candidates if str(c.get("entra_object_id") or "") == actor.entra_object_id),
        None,
    )
    if match is None:
        return base

    department = str(match.get("department") or actor.department)
    return ActorContext(
        entra_object_id=actor.entra_object_id,
        display_name=str(match.get("display_name") or actor.display_name),
        department=department,
        department_code=department_code(department),
        mail=str(match.get("mail") or ""),
        user_principal_name=str(match.get("upn") or ""),
        job_title=str(match.get("job_title") or ""),
    )


def _sender_user_ref(activity: Any) -> UserRef:
    sender = activity.from_
    oid = getattr(sender, "aad_object_id", None) or sender.id
    return UserRef(
        entra_object_id=str(oid),
        display_name=str(getattr(sender, "name", None) or ""),
        department="",
    )


async def build_turn_payload(
    activity: Any,
    *,
    search_users: Callable[[str], Awaitable[list[dict[str, Any]]]] | None = None,
    tool_profile: ToolProfile = "full",
    mention_overrides: dict[str, MentionResolution] | None = None,
    mention_result: MentionResolutionResult | None = None,
    actor: ActorContext | None = None,
) -> TurnPayload:
    actor_ref = _sender_user_ref(activity)
    if actor is None:
        actor = await enrich_actor(actor_ref, search_users)
    if mention_result is None:
        mention_result = await resolve_mentions_structured(
            activity,
            search_users=search_users,
            requester=actor,
            mention_overrides=mention_overrides,
        )
    message = redact(mention_result.message)
    conversation = activity.conversation
    enrichments = _build_enrichments(mention_result, mention_result.message)

    return TurnPayload(
        turn=TurnMeta(
            activity_id=str(getattr(activity, "id", "") or ""),
            timestamp=business_now().isoformat(),
        ),
        actor=actor,
        conversation=ConversationContext(
            id=str(getattr(conversation, "id", "") or ""),
            type=getattr(conversation, "conversation_type", None),
            is_group=getattr(conversation, "is_group", None),
        ),
        capabilities=CapabilitiesContext(
            graph_enabled=search_users is not None,
            tool_profile=tool_profile,
        ),
        message=message,
        enrichments=enrichments,
    )


def serialize_turn_payload(payload: TurnPayload) -> str:
    data = payload.model_dump(mode="json", exclude_none=True)
    # Transport correlation and conversation delivery fields are logged by the host;
    # the model only needs actor, capability, message, and enrichment context.
    data.pop("turn", None)
    data.pop("conversation", None)
    data["actor"] = {key: value for key, value in data["actor"].items() if value != ""}
    if payload.enrichments is not None:
        enrichments = data.get("enrichments", {})
        if not enrichments.get("task_references"):
            enrichments.pop("task_references", None)
        if enrichments.get("mentions"):
            mentions = enrichments["mentions"]
            if not mentions.get("resolved"):
                mentions.pop("resolved", None)
            if not mentions.get("ambiguous"):
                mentions.pop("ambiguous", None)
            if not mentions:
                enrichments.pop("mentions", None)
        if not enrichments:
            data.pop("enrichments", None)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
