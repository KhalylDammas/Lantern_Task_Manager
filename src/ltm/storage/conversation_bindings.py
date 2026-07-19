"""Persist Teams conversation references for proactive Bot Connector delivery (C03)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from microsoft_teams.api import ConversationReference

from ltm.storage.orm import ConversationBinding


class ConversationBindingRepository:
    def __init__(self, session: Session):
        self.s = session

    def upsert(self, user_entra_id: str, ref: ConversationReference) -> None:
        payload = ref.model_dump_json(by_alias=True)
        row = self.s.get(ConversationBinding, user_entra_id)
        if row is None:
            self.s.add(ConversationBinding(user_entra_id=user_entra_id, ref_json=payload))
        else:
            row.ref_json = payload
        self.s.flush()

    def get_ref(self, user_entra_id: str) -> ConversationReference | None:
        row = self.s.get(ConversationBinding, user_entra_id)
        if row is None:
            return None
        return ConversationReference.model_validate_json(row.ref_json)

