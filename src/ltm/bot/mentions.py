"""Resolve Teams @mentions into stable Entra object IDs for AI/tool use."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ltm.config.settings import get_settings
from ltm.domain.enums import DEPT_DISPLAY, DeptCode
from ltm.domain.models import UserRef
from ltm.interaction.normalization import normalize_routing_text

_AT_TAG_RE = re.compile(r"</?at>", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_PLAINTEXT_MENTION_RE = re.compile(
    r"(?<!\w)@([A-Za-z][A-Za-z0-9._-]*(?:\s+[A-Za-z][A-Za-z0-9._-]*){0,3})"
)
_MENTION_TRAILING_PUNCTUATION = ".,;:!?"
_MENTION_TRAILING_STOP_WORDS = {
    "a",
    "an",
    "and",
    "approve",
    "assign",
    "assigned",
    "at",
    "be",
    "by",
    "create",
    "due",
    "for",
    "from",
    "in",
    "is",
    "kindly",
    "normal",
    "of",
    "on",
    "or",
    "please",
    "priority",
    "review",
    "task",
    "the",
    "to",
    "type",
    "update",
    "updates",
    "with",
}
_LOWERCASE_NAME_PARTICLES = {"al", "bin", "bint", "de", "del", "der", "ibn", "van", "von"}


@dataclass(frozen=True)
class MentionResolution:
    token: str
    user: UserRef
    mail: str = ""
    upn: str = ""
    job_title: str = ""


@dataclass(frozen=True)
class AmbiguousMentionResolution:
    token: str
    query: str
    candidates: tuple[MentionResolution, ...]


@dataclass(frozen=True)
class MentionResolutionResult:
    message: str
    resolved: tuple[MentionResolution, ...]
    ambiguous: tuple[AmbiguousMentionResolution, ...]


def normalize_activity_text(text: str) -> str:
    """Strip Teams markup and collapse whitespace from inbound activity text."""
    return normalize_routing_text(_normalize_text(text))


def department_code(department: str) -> str:
    return _department_code(department)


def _normalize_text(text: str) -> str:
    normalized = _AT_TAG_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _looks_like_name_continuation(token: str) -> bool:
    lowered = token.lower()
    if lowered in _MENTION_TRAILING_STOP_WORDS:
        return False
    if token[:1].isupper():
        return True
    return lowered in _LOWERCASE_NAME_PARTICLES


def _normalize_plaintext_mention(raw: str) -> str:
    parts = [
        part.rstrip(_MENTION_TRAILING_PUNCTUATION)
        for part in _WHITESPACE_RE.split(raw.strip())
    ]
    if not parts:
        return ""
    name_parts = [parts[0]]
    for part in parts[1:]:
        if not _looks_like_name_continuation(part):
            break
        name_parts.append(part)
    return " ".join(name_parts)


def _department_code(department: str) -> str:
    normalized = department.strip().lower()
    if not normalized:
        return ""
    for code, display in DEPT_DISPLAY.items():
        if normalized in {code.value.lower(), display.lower()}:
            return code.value
    if normalized in {"operation", "operations", "op"}:
        return DeptCode.OP.value
    if normalized in {"procurement", "proc"}:
        return DeptCode.PROC.value
    if normalized in {"finance", "fin"}:
        return DeptCode.FIN.value
    if normalized in {"business development", "bizdev", "bd"}:
        return DeptCode.BD.value
    if normalized in {"sales", "sal"}:
        return DeptCode.SAL.value
    return ""


def _mention_from_candidate(token: str, candidate: dict[str, Any], fallback_name: str) -> MentionResolution:
    return MentionResolution(
        token=token,
        user=UserRef(
            entra_object_id=str(candidate["entra_object_id"]),
            display_name=str(candidate.get("display_name") or fallback_name),
            department=str(candidate.get("department") or ""),
        ),
        mail=str(candidate.get("mail") or ""),
        upn=str(candidate.get("upn") or ""),
        job_title=str(candidate.get("job_title") or ""),
    )


def _unique_candidate_mentions(
    token: str, candidates: list[dict[str, Any]], fallback_name: str
) -> list[MentionResolution]:
    mentions: list[MentionResolution] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        entra_id = str(candidate.get("entra_object_id") or "")
        if not entra_id or entra_id in seen_ids:
            continue
        seen_ids.add(entra_id)
        mentions.append(_mention_from_candidate(token, candidate, fallback_name))
    return mentions


def matching_identity_values(mention: MentionResolution) -> set[str]:
    return _matching_identity_values(mention)


def _matching_identity_values(mention: MentionResolution) -> set[str]:
    return {
        value.strip().lower()
        for value in (mention.user.display_name, mention.mail, mention.upn)
        if value and value.strip()
    }


def _single_exact_match(query: str, candidates: list[MentionResolution]) -> MentionResolution | None:
    normalized = query.strip().lower()
    exact = [candidate for candidate in candidates if normalized in _matching_identity_values(candidate)]
    return exact[0] if len(exact) == 1 else None


def _mention_context(mentions: list[MentionResolution]) -> str:
    lines = [
        "Directory-resolved mentioned users:",
        "Use these exact values for task assignee fields. Do not ask the user to share the user ID.",
    ]
    for mention in mentions:
        user = mention.user
        lines.extend(
            [
                f"- token: {mention.token}",
                f"  assignee_entra_id: {user.entra_object_id}",
                f"  assignee_display_name: {user.display_name or mention.token[1:]}",
                f"  assignee_department: {user.department}",
                f"  assignee_department_code: {_department_code(user.department)}",
            ]
        )
        if mention.mail:
            lines.append(f"  mail: {mention.mail}")
        if mention.upn:
            lines.append(f"  user_principal_name: {mention.upn}")
        if mention.job_title:
            lines.append(f"  job_title: {mention.job_title}")
    return "\n".join(lines)


def _ambiguity_context(ambiguities: list[AmbiguousMentionResolution]) -> str:
    lines = [
        "Ambiguous directory user matches:",
        "Do not call create_task for these mentions yet. Ask the requester to choose one listed user; do not ask for a raw user ID.",
    ]
    for ambiguity in ambiguities:
        lines.append(f"- token: {ambiguity.token}")
        lines.append(f"  query: {ambiguity.query}")
        lines.append("  candidates:")
        for index, candidate in enumerate(ambiguity.candidates, start=1):
            user = candidate.user
            lines.extend(
                [
                    f"    {index}. display_name: {user.display_name or candidate.token[1:]}",
                    f"       assignee_entra_id: {user.entra_object_id}",
                    f"       assignee_department: {user.department}",
                    f"       assignee_department_code: {_department_code(user.department)}",
                ]
            )
            if candidate.mail:
                lines.append(f"       mail: {candidate.mail}")
            if candidate.upn:
                lines.append(f"       user_principal_name: {candidate.upn}")
            if candidate.job_title:
                lines.append(f"       job_title: {candidate.job_title}")
    return "\n".join(lines)


def _entity_token(entity: Any) -> str | None:
    raw = getattr(entity, "text", None)
    if isinstance(raw, str) and raw.strip():
        cleaned = _normalize_text(raw)
        return cleaned if cleaned.startswith("@") else f"@{cleaned}"

    mentioned = getattr(entity, "mentioned", None)
    name = getattr(mentioned, "name", None)
    if isinstance(name, str) and name.strip():
        return f"@{name.strip()}"
    return None


def _user_from_mentioned(mentioned: Any) -> UserRef | None:
    if mentioned is None:
        return None
    entra_id = getattr(mentioned, "aad_object_id", None) or getattr(mentioned, "id", None)
    if not entra_id:
        return None
    return UserRef(
        entra_object_id=str(entra_id),
        display_name=str(getattr(mentioned, "name", None) or ""),
        department="",
    )


def extract_entity_mentions(activity: Any) -> list[MentionResolution]:
    results: list[MentionResolution] = []
    seen_ids: set[str] = set()
    for entity in getattr(activity, "entities", None) or []:
        if getattr(entity, "type", None) != "mention":
            continue
        token = _entity_token(entity)
        user = _user_from_mentioned(getattr(entity, "mentioned", None))
        if not token or user is None or user.entra_object_id in seen_ids:
            continue
        seen_ids.add(user.entra_object_id)
        results.append(MentionResolution(token=token, user=user))
    return results


def _replace_mentions(text: str, mentions: list[MentionResolution]) -> str:
    updated = text
    for mention in mentions:
        replacement = f"{mention.token} [EntraObjectId: {mention.user.entra_object_id}]"
        if mention.token in updated:
            updated = updated.replace(mention.token, replacement, 1)
            continue
        bare_name = mention.token[1:]
        if bare_name in updated:
            updated = updated.replace(bare_name, replacement, 1)
    return updated


def _pick_from_candidates(
    query: str,
    token: str,
    candidates: list[MentionResolution],
    requester: Any | None,
) -> Any:
    from ltm.bot.mention_scoring import rank_and_pick

    primary_domain = get_settings().primary_email_domain
    return rank_and_pick(query, candidates, requester, primary_email_domain=primary_domain)


async def _resolve_plaintext_mentions(
    text: str,
    search_users: Callable[[str], Awaitable[list[dict[str, Any]]]],
    *,
    requester: Any | None = None,
    mention_overrides: dict[str, MentionResolution] | None = None,
) -> tuple[list[MentionResolution], list[AmbiguousMentionResolution]]:
    found: list[MentionResolution] = []
    ambiguities: list[AmbiguousMentionResolution] = []
    seen_ids: set[str] = set()
    overrides = mention_overrides or {}
    for match in _PLAINTEXT_MENTION_RE.finditer(text):
        query = _normalize_plaintext_mention(match.group(1))
        if not query:
            continue
        token = f"@{query}"
        if token in overrides:
            resolved = overrides[token]
            if resolved.user.entra_object_id in seen_ids:
                continue
            seen_ids.add(resolved.user.entra_object_id)
            found.append(resolved)
            continue

        candidates = _unique_candidate_mentions(token, await search_users(query), query)
        if not candidates:
            continue

        pick = _pick_from_candidates(query, token, candidates, requester)
        if pick.resolved is None:
            ambiguities.append(
                AmbiguousMentionResolution(
                    token=token,
                    query=query,
                    candidates=pick.ranked_candidates or tuple(candidates),
                )
            )
            continue

        if pick.resolved.user.entra_object_id in seen_ids:
            continue
        seen_ids.add(pick.resolved.user.entra_object_id)
        found.append(pick.resolved)
    return found, ambiguities


async def resolve_assignee_name(
    query: str,
    search_users: Callable[[str], Awaitable[list[dict[str, Any]]]],
    *,
    requester: Any | None = None,
) -> Any:
    """Resolve a human name (manual form or ad hoc) using directory search and scoring."""
    from ltm.bot.mention_scoring import RankPickResult

    normalized = query.strip()
    if not normalized:
        return RankPickResult(resolved=None, ranked_candidates=())
    token = f"@{normalized}"
    candidates = _unique_candidate_mentions(token, await search_users(normalized), normalized)
    if not candidates:
        return RankPickResult(resolved=None, ranked_candidates=())
    return _pick_from_candidates(normalized, token, candidates, requester)


async def _enrich_entity_mentions(
    mentions: list[MentionResolution],
    search_users: Callable[[str], Awaitable[list[dict[str, Any]]]],
) -> list[MentionResolution]:
    enriched: list[MentionResolution] = []
    for mention in mentions:
        query = mention.user.display_name or mention.token[1:]
        if not query:
            enriched.append(mention)
            continue
        candidates = await search_users(query)
        match = next(
            (c for c in candidates if str(c.get("entra_object_id") or "") == mention.user.entra_object_id),
            None,
        )
        if match is None:
            enriched.append(mention)
            continue
        enriched.append(
            MentionResolution(
                token=mention.token,
                user=UserRef(
                    entra_object_id=mention.user.entra_object_id,
                    display_name=str(match.get("display_name") or mention.user.display_name),
                    department=str(match.get("department") or mention.user.department),
                ),
                mail=str(match.get("mail") or ""),
                upn=str(match.get("upn") or ""),
                job_title=str(match.get("job_title") or ""),
            )
        )
    return enriched


async def resolve_mentions_structured(
    activity: Any,
    *,
    search_users: Callable[[str], Awaitable[list[dict[str, Any]]]] | None = None,
    requester: Any | None = None,
    mention_overrides: dict[str, MentionResolution] | None = None,
) -> MentionResolutionResult:
    """Resolve Teams mentions into structured data and inline Entra IDs in the message body."""

    text = _normalize_text(getattr(activity, "text", "") or "")
    overrides = dict(mention_overrides or {})
    mentions = extract_entity_mentions(activity)
    ambiguities: list[AmbiguousMentionResolution] = []

    if mentions and search_users is not None:
        mentions = await _enrich_entity_mentions(mentions, search_users)

    if overrides:
        merged: list[MentionResolution] = []
        seen_ids: set[str] = set()
        for mention in mentions:
            picked = overrides.get(mention.token, mention)
            if picked.user.entra_object_id in seen_ids:
                continue
            seen_ids.add(picked.user.entra_object_id)
            merged.append(picked)
        for override in overrides.values():
            if override.user.entra_object_id in seen_ids:
                continue
            seen_ids.add(override.user.entra_object_id)
            merged.append(override)
        mentions = merged

    if not mentions and search_users is not None:
        mentions, ambiguities = await _resolve_plaintext_mentions(
            text,
            search_users,
            requester=requester,
            mention_overrides=overrides,
        )

    rewritten = _replace_mentions(text, mentions) if mentions else text
    return MentionResolutionResult(
        message=rewritten,
        resolved=tuple(mentions),
        ambiguous=tuple(ambiguities),
    )


async def resolve_mentions_in_text(
    activity: Any,
    *,
    search_users: Callable[[str], Awaitable[list[dict[str, Any]]]] | None = None,
) -> str:
    """Legacy string format with prose directory blocks (prefer resolve_mentions_structured)."""

    result = await resolve_mentions_structured(activity, search_users=search_users)
    if not result.resolved and not result.ambiguous:
        return result.message

    context_blocks: list[str] = []
    if result.resolved:
        context_blocks.append(_mention_context(list(result.resolved)))
    if result.ambiguous:
        context_blocks.append(_ambiguity_context(list(result.ambiguous)))
    return f"{result.message}\n\n" + "\n\n".join(context_blocks)
