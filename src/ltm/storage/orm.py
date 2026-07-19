"""SQLAlchemy ORM (C06)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ltm.domain.business_time import business_now


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return business_now()


class TaskCounter(Base):
    __tablename__ = "ltm_task_counters"
    __table_args__ = (UniqueConstraint("department_code", "year", name="uq_counter_dept_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department_code: Mapped[str] = mapped_column(String(8), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TaskORM(Base):
    __tablename__ = "ltm_tasks"

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(200), nullable=False)
    department_display: Mapped[str] = mapped_column(String(120), nullable=False)
    department_code: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(24), nullable=False)

    created_by_entra_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by_display_name: Mapped[str] = mapped_column(String(256), default="")
    created_by_department: Mapped[str] = mapped_column(String(120), default="")

    assigned_to_entra_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    assigned_to_display_name: Mapped[str] = mapped_column(String(256), default="")
    assigned_to_department: Mapped[str] = mapped_column(String(120), default="")

    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_notes: Mapped[str] = mapped_column(Text, default="")
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_count: Mapped[int] = mapped_column(Integer, default=0)
    last_escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    d365_references: Mapped[dict] = mapped_column(JSON, default=dict)
    audit_trail: Mapped[list] = mapped_column(JSON, default=list)


class IdempotencyRecord(Base):
    __tablename__ = "ltm_idempotency"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    payload: Mapped[str] = mapped_column(Text, default="{}")


class ConversationBinding(Base):
    """Persist Bot Framework ConversationReference keyed by user's Entra object id (C03)."""

    __tablename__ = "ltm_conversation_bindings"

    user_entra_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ref_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class NotificationDeliveryORM(Base):
    """Delivery log / outbox for proactive notifications."""

    __tablename__ = "ltm_notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    recipient_entra_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    activity_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_dm_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_retry: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LlmUsageDaily(Base):
    """Daily LLM usage aggregates for governance (C09)."""

    __tablename__ = "ltm_llm_usage_daily"

    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
