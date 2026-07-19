"""Optional integration test against a real Turso database.

Skipped unless TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set (not run in CI).
Run manually: TURSO_DATABASE_URL=… TURSO_AUTH_TOKEN=… pytest tests/test_turso_integration.py -v
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest

_HAS_TURSO = bool(os.environ.get("TURSO_DATABASE_URL")) and bool(os.environ.get("TURSO_AUTH_TOKEN"))

pytestmark = pytest.mark.skipif(not _HAS_TURSO, reason="TURSO_DATABASE_URL / TURSO_AUTH_TOKEN not set")


@pytest.fixture
def turso_engine(monkeypatch):
    """Point the engine at remote Turso instead of the conftest in-memory override."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from ltm.config.settings import clear_settings_cache
    from ltm.storage import db as db_mod
    from ltm.storage.orm import Base

    clear_settings_cache()
    db_mod.reset_engine()
    eng = db_mod.engine()
    # Integration convenience: ensure schema exists (idempotent; Alembic owns deploys).
    Base.metadata.create_all(eng)
    yield eng
    db_mod.reset_engine()
    clear_settings_cache()


def test_repository_round_trip_on_turso(turso_engine):
    from ltm.domain.enums import DeptCode
    from ltm.domain.models import TaskCreateDraft, UserRef
    from ltm.storage.db import session_scope
    from ltm.storage.repository import TaskRepository

    requester = UserRef(
        entra_object_id=str(uuid.uuid4()),
        display_name="Turso Integration Requester",
        department="IT",
    )
    draft = TaskCreateDraft(
        task_type="LC Opening",
        description="turso integration round-trip",
        assignee_entra_id=str(uuid.uuid4()),
        assignee_display_name="Turso Integration Assignee",
        assignee_department="IT",
        assignee_department_code=DeptCode.IT,
        priority="Low",
        due_date=date(2026, 12, 31),
    )

    with session_scope() as s:
        rec = TaskRepository(s).create_from_draft(draft, requester)
        task_id = rec.id

    with session_scope() as s:
        back = TaskRepository(s).get(task_id)
        assert back is not None
        assert back.assigned_to.display_name == "Turso Integration Assignee"
        assert len(back.audit_trail) >= 1
