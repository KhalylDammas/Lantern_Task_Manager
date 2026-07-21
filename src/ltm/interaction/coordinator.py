"""Canonical response receipts for idempotent inbound card actions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from ltm.storage.db import session_scope
from ltm.storage.orm import IdempotencyRecord
from ltm.domain.business_time import business_now

_CLAIM_TIMEOUT = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class StoredResponse:
    code: str
    text: str


class ResponseCoordinator:
    @staticmethod
    def enabled() -> bool:
        from ltm.config.settings import get_settings

        return get_settings().interaction_coordinator_enabled

    @staticmethod
    def action_key(*, action_token: str, activity_id: str, actor_id: str,
                   verb: str, reference_id: str) -> str:
        stable_token = action_token or (
            f"legacy:{reference_id}" if reference_id else f"legacy:{activity_id}"
        )
        raw = f"card:{stable_token}:{actor_id}:{verb}:{reference_id}".encode()
        return f"action:{hashlib.sha256(raw).hexdigest()}"

    def claim(self, key: str) -> tuple[bool, StoredResponse | None]:
        if not self.enabled():
            return True, None
        try:
            with session_scope() as session:
                existing = session.get(IdempotencyRecord, key)
                if existing is not None:
                    payload = json.loads(existing.payload or "{}")
                    processed_at = existing.processed_at
                    now = business_now()
                    if processed_at.tzinfo is None:
                        now = now.replace(tzinfo=None)
                    if (payload.get("code") == "IN_PROGRESS"
                            and processed_at < now - _CLAIM_TIMEOUT):
                        existing.processed_at = business_now()
                        existing.payload = '{"code":"IN_PROGRESS"}'
                        return True, None
                    return False, StoredResponse(str(payload.get("code") or "IN_PROGRESS"),
                                                 str(payload.get("text") or "This action is already being processed."))
                session.add(IdempotencyRecord(key=key, payload='{"code":"IN_PROGRESS"}'))
            return True, None
        except IntegrityError:
            return False, StoredResponse("IN_PROGRESS", "This action is already being processed.")

    def complete(self, key: str, *, code: str, text: str) -> None:
        if not self.enabled():
            return
        with session_scope() as session:
            row = session.get(IdempotencyRecord, key)
            if row is not None:
                row.payload = json.dumps({"code": code, "text": text})
                row.processed_at = business_now()
