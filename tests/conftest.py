"""Test defaults: in-memory SQLite and fresh engine singleton."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def sqlite_memory_engine():
    os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
    os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

    from ltm.config.settings import clear_settings_cache

    clear_settings_cache()
    from ltm.storage import db as db_mod

    db_mod.reset_engine()
    yield
    db_mod.reset_engine()
    clear_settings_cache()
