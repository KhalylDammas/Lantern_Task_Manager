from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ltm.domain.business_time import business_now
from ltm.interaction.models import InteractionOperation
from ltm.storage.db import session_scope
from ltm.storage.orm import InteractionSessionORM

_TTL = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class PendingInteraction:
    revision: int
    operation: InteractionOperation | None
    slots: dict[str, Any]
    missing_fields: tuple[str, ...]
    reference_id: str


class InteractionStore:
    @staticmethod
    def enabled() -> bool:
        from ltm.config.settings import get_settings

        return get_settings().interaction_coordinator_enabled

    def begin_event(self, *, actor_id: str, conversation_id: str, activity_id: str = "") -> int:
        if not self.enabled():
            return 0
        with session_scope() as session:
            self._row(session, actor_id, conversation_id)
            session.execute(
                update(InteractionSessionORM).where(
                    InteractionSessionORM.actor_entra_id == actor_id,
                    InteractionSessionORM.conversation_id == conversation_id,
                ).values(
                    revision=InteractionSessionORM.revision + 1,
                    source_activity_id=activity_id,
                    updated_at=business_now(),
                )
            )
            revision = session.scalar(select(InteractionSessionORM.revision).where(
                InteractionSessionORM.actor_entra_id == actor_id,
                InteractionSessionORM.conversation_id == conversation_id,
            ))
            return int(revision or 0)

    def set_pending(self, *, actor_id: str, conversation_id: str, operation: InteractionOperation,
                    slots: dict[str, Any], missing_fields: list[str], reference_id: str = "",
                    expected_revision: int | None = None) -> int | None:
        if not self.enabled():
            return None
        with session_scope() as session:
            row = self._row(session, actor_id, conversation_id)
            if expected_revision is not None:
                changed = session.execute(
                    update(InteractionSessionORM).where(
                        InteractionSessionORM.id == row.id,
                        InteractionSessionORM.revision == expected_revision,
                    ).values(
                        active_operation=operation.value, slots=dict(slots),
                        missing_fields=list(missing_fields), reference_id=reference_id,
                        expires_at=business_now() + _TTL, updated_at=business_now(),
                    )
                )
                return expected_revision if changed.rowcount == 1 else None
            row.active_operation = operation.value
            row.slots = dict(slots)
            row.missing_fields = list(missing_fields)
            row.reference_id = reference_id
            row.expires_at = business_now() + _TTL
            row.updated_at = business_now()
            return row.revision

    def get(self, *, actor_id: str, conversation_id: str) -> PendingInteraction | None:
        if not self.enabled():
            return None
        with session_scope() as session:
            row = session.scalar(select(InteractionSessionORM).where(
                InteractionSessionORM.actor_entra_id == actor_id,
                InteractionSessionORM.conversation_id == conversation_id,
            ))
            if row is None:
                return None
            now = business_now()
            if row.expires_at and row.expires_at.tzinfo is None:
                now = now.replace(tzinfo=None)
            if row.expires_at and row.expires_at < now:
                self._clear_row(row)
                return None
            operation = InteractionOperation(row.active_operation) if row.active_operation else None
            return PendingInteraction(row.revision, operation, dict(row.slots or {}),
                                      tuple(row.missing_fields or []), row.reference_id)

    def clear(self, *, actor_id: str, conversation_id: str) -> None:
        if not self.enabled():
            return
        with session_scope() as session:
            row = session.scalar(select(InteractionSessionORM).where(
                InteractionSessionORM.actor_entra_id == actor_id,
                InteractionSessionORM.conversation_id == conversation_id,
            ))
            if row:
                self._clear_row(row)

    def is_current(self, *, actor_id: str, conversation_id: str, revision: int) -> bool:
        if not self.enabled():
            return True
        current = self.get(actor_id=actor_id, conversation_id=conversation_id)
        return current is not None and current.revision == revision

    @staticmethod
    def _row(session, actor_id: str, conversation_id: str) -> InteractionSessionORM:
        row = session.scalar(select(InteractionSessionORM).where(
            InteractionSessionORM.actor_entra_id == actor_id,
            InteractionSessionORM.conversation_id == conversation_id,
        ))
        if row is None:
            row = InteractionSessionORM(actor_entra_id=actor_id, conversation_id=conversation_id,
                                         slots={}, missing_fields=[])
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                row = session.scalar(select(InteractionSessionORM).where(
                    InteractionSessionORM.actor_entra_id == actor_id,
                    InteractionSessionORM.conversation_id == conversation_id,
                ))
                if row is None:
                    raise
        return row

    @staticmethod
    def _clear_row(row: InteractionSessionORM) -> None:
        row.active_operation = ""
        row.slots = {}
        row.missing_fields = []
        row.reference_id = ""
        row.expires_at = None
        row.updated_at = business_now()
