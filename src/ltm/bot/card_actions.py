"""Routing for task card actions, independent of the Teams SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ltm.application import DraftUseCases, TaskUseCases, UseCaseResult
from ltm.domain.models import CloseTaskParams, TaskRecord, UserRef

CardValue = TaskRecord | str
Handler = Callable[[dict[str, Any], UserRef], Awaitable[UseCaseResult[CardValue]]]


@dataclass(frozen=True, slots=True)
class CardActionDispatch:
    handled: bool
    result: UseCaseResult[CardValue] | None = None


def _missing(field: str) -> UseCaseResult[CardValue]:
    return UseCaseResult.failure(code=f"MISSING_{field.upper()}", message=f"Missing {field.replace('_', ' ')}.")


def _text(data: dict[str, Any], field: str) -> str | None:
    value = data.get(field)
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _confirm_draft(data: dict[str, Any], actor: UserRef) -> UseCaseResult[CardValue]:
    draft_id = _text(data, "draft_id")
    return await DraftUseCases().confirm(draft_id, actor) if draft_id else _missing("draft_id")


async def _cancel_draft(data: dict[str, Any], actor: UserRef) -> UseCaseResult[CardValue]:
    draft_id = _text(data, "draft_id")
    return DraftUseCases().cancel(draft_id, actor) if draft_id else _missing("draft_id")


async def _view(data: dict[str, Any], actor: UserRef) -> UseCaseResult[CardValue]:
    task_id = _text(data, "task_id")
    return TaskUseCases().get_task(task_id, actor) if task_id else _missing("task_id")


async def _acknowledge(data: dict[str, Any], actor: UserRef) -> UseCaseResult[CardValue]:
    task_id = _text(data, "task_id")
    return TaskUseCases().acknowledge(task_id, actor) if task_id else _missing("task_id")


async def _resume(data: dict[str, Any], actor: UserRef) -> UseCaseResult[CardValue]:
    task_id = _text(data, "task_id")
    return TaskUseCases().resume(task_id, actor) if task_id else _missing("task_id")


async def _close(data: dict[str, Any], actor: UserRef) -> UseCaseResult[CardValue]:
    task_id = _text(data, "task_id")
    notes = _text(data, "completion_notes")
    if not task_id:
        return _missing("task_id")
    if not notes:
        return UseCaseResult.failure(code="MISSING_COMPLETION_NOTES", message="Completion notes required.")
    return await TaskUseCases().close(CloseTaskParams(task_id=task_id, completion_notes=notes), actor)


async def _verify(data: dict[str, Any], actor: UserRef) -> UseCaseResult[CardValue]:
    task_id = _text(data, "task_id")
    return await TaskUseCases().verify(task_id, actor) if task_id else _missing("task_id")


async def _reject(data: dict[str, Any], actor: UserRef) -> UseCaseResult[CardValue]:
    task_id = _text(data, "task_id")
    reason = _text(data, "rejection_reason")
    if not task_id:
        return _missing("task_id")
    if not reason:
        return UseCaseResult.failure(code="MISSING_REASON", message="Rejection reason required.")
    return await TaskUseCases().reopen(task_id, reason, actor)


_HANDLERS: dict[str, Handler] = {
    "draft.confirm": _confirm_draft,
    "confirm_task": _confirm_draft,  # one-release compatibility alias
    "draft.cancel": _cancel_draft,
    "cancel_draft": _cancel_draft,  # one-release compatibility alias
    "task.view": _view,
    "view_task": _view,  # one-release compatibility alias
    "task.acknowledge": _acknowledge,
    "ack_task": _acknowledge,  # one-release compatibility alias
    "task.resume": _resume,
    "resume_task": _resume,  # one-release compatibility alias
    "task.close": _close,
    "close_task": _close,  # one-release compatibility alias
    "task.verify": _verify,
    "manager_verify_confirm": _verify,  # one-release compatibility alias
    "task.reject": _reject,
    "manager_verify_reject": _reject,  # one-release compatibility alias
}


async def dispatch_card_action(verb: str | None, data: dict[str, Any], actor: UserRef) -> CardActionDispatch:
    handler = _HANDLERS.get(verb or "")
    if handler is None:
        return CardActionDispatch(handled=False)
    return CardActionDispatch(handled=True, result=await handler(data, actor))
