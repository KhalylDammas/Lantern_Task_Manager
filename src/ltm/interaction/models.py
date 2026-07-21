from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from ltm.domain.enums import TaskStatus


class InteractionOperation(StrEnum):
    CREATE_TASK = "CREATE_TASK"
    REVIEW_DRAFT = "REVIEW_DRAFT"
    CLOSE_TASK = "CLOSE_TASK"
    REOPEN_TASK = "REOPEN_TASK"


class DraftCandidate(BaseModel):
    """Partial natural-language capture before required slots are complete."""

    task_type: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1, max_length=8000)
    assignee: str | None = None
    assignee_entra_id: str | None = None
    assignee_display_name: str = ""
    priority: str | None = None
    due_date: str | None = None
    purchase_order_number: str | None = None
    vendor_account: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    customer_account: str | None = None
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class InteractionOrigin:
    actor_entra_id: str
    conversation_id: str = ""
    conversation_type: str = ""
    activity_id: str = ""
    source: Literal["message", "card_action", "system"] = "message"


@dataclass(frozen=True, slots=True)
class InteractionResponse:
    code: str
    text: str = ""
    card: Any | None = None
    resulting_state: TaskStatus | None = None
