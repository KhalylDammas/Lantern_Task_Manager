"""Connection precedence: DATABASE_URL → Turso → Azure SQL → error (Unit #8)."""

from __future__ import annotations

import os

import pytest

from ltm.config.settings import clear_settings_cache
from ltm.storage.engine_config import (
    EngineConfig,
    build_engine_config,
    build_turso_sqlalchemy_url,
    normalize_turso_url,
)


@pytest.fixture
def clean_db_env(monkeypatch):
    for var in ("DATABASE_URL", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "AZURE_SQL_ODBC_CONNECTION_STRING"):
        monkeypatch.setenv(var, "")
    clear_settings_cache()
    # Unit tests validate resolution, not public Turso connectivity.
    monkeypatch.setattr("ltm.storage.engine_config._turso_hrana_reachable", lambda *_: True)
    yield monkeypatch
    clear_settings_cache()


def test_database_url_override_wins(clean_db_env):
    clean_db_env.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    clean_db_env.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    clean_db_env.setenv("TURSO_AUTH_TOKEN", "token")
    clear_settings_cache()

    cfg = build_engine_config()
    assert cfg.backend == "override"
    assert cfg.url == "sqlite+pysqlite:///:memory:"
    assert cfg.connect_args == {}
    assert cfg.is_memory


def test_turso_selected_when_url_and_token_set(clean_db_env):
    clean_db_env.setenv("TURSO_DATABASE_URL", "libsql://ltm-dev.turso.io")
    clean_db_env.setenv("TURSO_AUTH_TOKEN", "secret-token")
    clear_settings_cache()

    cfg = build_engine_config()
    assert cfg.backend == "turso"
    assert cfg.url == "sqlite+libsql://ltm-dev.turso.io?secure=true"
    assert cfg.connect_args == {"auth_token": "secret-token"}
    assert not cfg.is_memory


def test_turso_accepts_sqlalchemy_url_without_double_prefix(clean_db_env):
    clean_db_env.setenv("TURSO_DATABASE_URL", "sqlite+libsql://ltm-dev.turso.io")
    clean_db_env.setenv("TURSO_AUTH_TOKEN", "secret-token")
    clear_settings_cache()

    cfg = build_engine_config()
    assert cfg.backend == "turso"
    assert cfg.url == "sqlite+libsql://ltm-dev.turso.io?secure=true"


def test_turso_uses_sync_replica_when_hrana_is_blocked(clean_db_env):
    clean_db_env.setenv("TURSO_DATABASE_URL", "libsql://ltm-dev.turso.io")
    clean_db_env.setenv("TURSO_AUTH_TOKEN", "secret-token")
    clean_db_env.setattr("ltm.storage.engine_config._turso_hrana_reachable", lambda *_: False)
    clean_db_env.setattr("ltm.storage.engine_config.probe_turso_http_pipeline", lambda **_: (True, None))
    clean_db_env.setattr(
        "ltm.storage.engine_config._build_sync_engine_config",
        lambda *_: EngineConfig(url="sqlite+pysqlite:////tmp/ltm-replica.db", backend="turso"),
    )
    clear_settings_cache()

    cfg = build_engine_config()
    assert cfg.backend == "turso"
    assert cfg.url == "sqlite+pysqlite:////tmp/ltm-replica.db"


def test_turso_requires_both_url_and_token(clean_db_env):
    clean_db_env.setenv("TURSO_DATABASE_URL", "libsql://ltm-dev.turso.io")
    clean_db_env.setenv("AZURE_SQL_ODBC_CONNECTION_STRING", "Driver={ODBC Driver 18 for SQL Server};Server=tcp:x")
    clear_settings_cache()

    cfg = build_engine_config()
    assert cfg.backend == "azure_sql"


def test_azure_sql_fallback(clean_db_env):
    clean_db_env.setenv("AZURE_SQL_ODBC_CONNECTION_STRING", "Driver={ODBC Driver 18 for SQL Server};Server=tcp:x")
    clear_settings_cache()

    cfg = build_engine_config()
    assert cfg.backend == "azure_sql"
    assert cfg.url.startswith("mssql+pyodbc:///?odbc_connect=")
    assert cfg.connect_args == {}


def test_no_configuration_raises(clean_db_env):
    with pytest.raises(RuntimeError, match="No database configured"):
        build_engine_config()


def test_normalize_turso_url_adds_scheme():
    assert normalize_turso_url("ltm-dev.turso.io") == "libsql://ltm-dev.turso.io"
    assert normalize_turso_url("libsql://ltm-dev.turso.io") == "libsql://ltm-dev.turso.io"
    assert normalize_turso_url("sqlite+libsql://ltm-dev.turso.io") == "libsql://ltm-dev.turso.io"


def test_normalize_turso_url_rejects_empty():
    with pytest.raises(ValueError):
        normalize_turso_url("  ")


def test_normalize_turso_url_rejects_unsupported_scheme():
    with pytest.raises(ValueError, match="libsql://"):
        normalize_turso_url("https://ltm-dev.turso.io")


def test_build_turso_sqlalchemy_url_preserves_existing_query():
    assert (
        build_turso_sqlalchemy_url("libsql://ltm-dev.turso.io?secure=true")
        == "sqlite+libsql://ltm-dev.turso.io?secure=true"
    )
    assert (
        build_turso_sqlalchemy_url("libsql://ltm-dev.turso.io?replica=primary")
        == "sqlite+libsql://ltm-dev.turso.io?replica=primary&secure=true"
    )
