"""Score directory candidates for @mention and assignee name resolution.

Signals (additive weights):
- +4 exact identity match on display name, mail, or UPN
- +3 primary email domain (@lanternsystems.com by default)
- -2 onmicrosoft.com-only identity when primary domain absent
- +3 candidate department aligns with requester department code
- +5 candidate's manager matches requester entra_object_id (assignment directory)

Auto-pick when top score beats second by >= AUTO_PICK_MARGIN (default 2), or second is 0 and top >= 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ltm.bot.mentions import MentionResolution, department_code, matching_identity_values
from ltm.policy.errors import ProfileNotFound
from ltm.policy.profiles import get_profile

AUTO_PICK_MARGIN = 2
WEIGHT_EXACT = 4
WEIGHT_PRIMARY_DOMAIN = 3
WEIGHT_ONMICROSOFT_PENALTY = 2
WEIGHT_DEPARTMENT = 3
WEIGHT_DIRECT_REPORT = 5


@dataclass(frozen=True)
class RankPickResult:
    resolved: MentionResolution | None
    ranked_candidates: tuple[MentionResolution, ...]


def _requester_entra_id(requester: Any | None) -> str:
    if requester is None:
        return ""
    return str(getattr(requester, "entra_object_id", "") or "")


def _requester_department_code(requester: Any | None) -> str:
    if requester is None:
        return ""
    code = str(getattr(requester, "department_code", "") or "").strip()
    if code:
        return code
    department = str(getattr(requester, "department", "") or "")
    return department_code(department)


def _candidate_manager_entra_id(entra_object_id: str) -> str | None:
    try:
        return get_profile(entra_object_id).manager_entra_id
    except ProfileNotFound:
        return None


def _has_primary_domain(candidate: MentionResolution, primary_email_domain: str) -> bool:
    suffix = f"@{primary_email_domain.strip().lower().lstrip('@')}"
    for value in (candidate.mail, candidate.upn):
        if value and value.strip().lower().endswith(suffix):
            return True
    return False


def _is_onmicrosoft_only(candidate: MentionResolution, primary_email_domain: str) -> bool:
    if _has_primary_domain(candidate, primary_email_domain):
        return False
    for value in (candidate.mail, candidate.upn):
        lowered = value.strip().lower()
        if lowered.endswith(".onmicrosoft.com"):
            return True
    return False


def score_candidate(
    query: str,
    candidate: MentionResolution,
    requester: Any | None,
    *,
    primary_email_domain: str,
) -> int:
    normalized_query = query.strip().lower()
    if normalized_query in matching_identity_values(candidate):
        score = WEIGHT_EXACT
    else:
        score = 0

    if _has_primary_domain(candidate, primary_email_domain):
        score += WEIGHT_PRIMARY_DOMAIN
    if _is_onmicrosoft_only(candidate, primary_email_domain):
        score -= WEIGHT_ONMICROSOFT_PENALTY

    requester_dept = _requester_department_code(requester)
    candidate_dept = department_code(candidate.user.department)
    if requester_dept and candidate_dept and requester_dept == candidate_dept:
        score += WEIGHT_DEPARTMENT

    requester_id = _requester_entra_id(requester)
    manager_id = _candidate_manager_entra_id(candidate.user.entra_object_id)
    if requester_id and manager_id and requester_id == manager_id:
        score += WEIGHT_DIRECT_REPORT

    return score


def rank_and_pick(
    query: str,
    candidates: list[MentionResolution],
    requester: Any | None,
    *,
    primary_email_domain: str = "lanternsystems.com",
) -> RankPickResult:
    if not candidates:
        return RankPickResult(resolved=None, ranked_candidates=())
    if len(candidates) == 1:
        return RankPickResult(resolved=candidates[0], ranked_candidates=tuple(candidates))

    exact_matches = [
        candidate
        for candidate in candidates
        if query.strip().lower() in matching_identity_values(candidate)
    ]
    if len(exact_matches) == 1:
        return RankPickResult(resolved=exact_matches[0], ranked_candidates=tuple(candidates))

    scored = sorted(
        (
            (score_candidate(query, candidate, requester, primary_email_domain=primary_email_domain), candidate)
            for candidate in candidates
        ),
        key=lambda item: (-item[0], item[1].user.display_name.lower()),
    )
    ranked = tuple(candidate for _, candidate in scored)
    top_score, top = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0

    if top_score <= 0 and second_score <= 0:
        return RankPickResult(resolved=None, ranked_candidates=ranked)

    margin = top_score - second_score
    if margin >= AUTO_PICK_MARGIN:
        return RankPickResult(resolved=top, ranked_candidates=ranked)
    if second_score == 0 and top_score >= WEIGHT_EXACT:
        return RankPickResult(resolved=top, ranked_candidates=ranked)
    if second_score > 0 and margin >= AUTO_PICK_MARGIN and margin / second_score >= 0.25:
        return RankPickResult(resolved=top, ranked_candidates=ranked)

    return RankPickResult(resolved=None, ranked_candidates=ranked)
