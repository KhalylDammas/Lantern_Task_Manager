"""Shared engine resolution (C06): DATABASE_URL → Turso → Azure SQL ODBC.

Used by both the runtime engine factory (db.py) and Alembic (alembic/env.py)
so connection precedence is defined in exactly one place.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ltm.config.settings import get_settings

logger = logging.getLogger(__name__)

Backend = Literal["override", "turso", "azure_sql"]


def turso_host_from_url(raw: str) -> str:
    url = raw.strip()
    for prefix in ("sqlite+libsql://", "libsql://"):
        if url.startswith(prefix):
            url = url.removeprefix(prefix)
            break
    return urlsplit(f"//{url}" if "://" not in url else url).netloc or "unknown"


@dataclass(frozen=True)
class TursoSyncConfig:
    local_path: str
    remote_url: str
    auth_token: str


@dataclass(frozen=True)
class EngineConfig:
    url: str
    backend: Backend
    connect_args: dict = field(default_factory=dict)
    turso_sync: TursoSyncConfig | None = None

    @property
    def is_memory(self) -> bool:
        return ":memory:" in self.url


def normalize_turso_url(raw: str) -> str:
    """Return a `libsql://host` URL from a raw TURSO_DATABASE_URL value."""
    url = raw.strip()
    if not url:
        raise ValueError("TURSO_DATABASE_URL is empty")
    if url.startswith("sqlite+libsql://"):
        return "libsql://" + url.removeprefix("sqlite+libsql://")
    if url.startswith("libsql://"):
        return url
    if "://" in url:
        raise ValueError("TURSO_DATABASE_URL must be a libsql:// or sqlite+libsql:// URL")
    return f"libsql://{url}"


def build_turso_sqlalchemy_url(raw: str) -> str:
    """Return the SQLAlchemy URL for a remote Turso libSQL database."""
    normalized = normalize_turso_url(raw)
    parts = urlsplit(normalized)
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key == "secure" for key, _ in query_items):
        query_items.append(("secure", "true"))
    remote_url = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query_items),
            parts.fragment,
        )
    )
    return f"sqlite+{remote_url}"


def _turso_hrana_reachable(turso_url: str, turso_token: str) -> bool:
    eng = None
    try:
        eng = create_engine(
            build_turso_sqlalchemy_url(turso_url),
            connect_args={"auth_token": turso_token},
            pool_pre_ping=True,
        )
        with eng.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if eng is not None:
            eng.dispose()


def _build_sync_engine_config(turso_url: str, turso_token: str) -> EngineConfig:
    from ltm.storage.turso_sync import default_local_replica_path, pull_replica

    local_path = default_local_replica_path()
    remote_url = normalize_turso_url(turso_url)
    sync = TursoSyncConfig(local_path=str(local_path), remote_url=remote_url, auth_token=turso_token)
    pull_replica(sync)
    return EngineConfig(
        url=f"sqlite+pysqlite:///{local_path}",
        backend="turso",
        connect_args={"check_same_thread": False},
        turso_sync=sync,
    )


def resolve_turso_engine_config(turso_url: str, turso_token: str) -> EngineConfig:
    force_sync = (os.environ.get("TURSO_FORCE_SYNC") or "").strip().lower() in {"1", "true", "yes"}
    hrana_ok = False if force_sync else _turso_hrana_reachable(turso_url, turso_token)

    if hrana_ok:
        return EngineConfig(
            url=build_turso_sqlalchemy_url(turso_url),
            backend="turso",
            connect_args={"auth_token": turso_token},
        )

    http_ok, http_err = probe_turso_http_pipeline(database_url=turso_url, auth_token=turso_token)
    if not http_ok:
        raise RuntimeError(f"Turso unreachable (Hrana and HTTP pipeline failed): {http_err}")

    logger.warning(
        "Turso Hrana WebSocket unavailable for %s; using local pyturso sync replica",
        turso_host_from_url(turso_url),
    )
    cfg = _build_sync_engine_config(turso_url, turso_token)
    return cfg


def build_engine_config() -> EngineConfig:
    direct = (os.environ.get("DATABASE_URL") or "").strip()
    if direct:
        return EngineConfig(url=direct, backend="override")

    settings = get_settings()

    turso_url = (settings.turso_database_url or "").strip()
    turso_token = (settings.turso_auth_token or "").strip()
    if turso_url and turso_token:
        return resolve_turso_engine_config(turso_url, turso_token)

    odbc = (settings.azure_sql_odbc_connection_string or "").strip()
    if odbc:
        return EngineConfig(
            url="mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc),
            backend="azure_sql",
        )

    raise RuntimeError(
        "No database configured. Set DATABASE_URL, or TURSO_DATABASE_URL + "
        "TURSO_AUTH_TOKEN, or AZURE_SQL_ODBC_CONNECTION_STRING. "
        "See docs/LTM_LOCAL_SETUP.md."
    )


def probe_turso_http_pipeline(*, database_url: str, auth_token: str, timeout: float = 10.0) -> tuple[bool, str | None]:
    """Check Turso HTTP /v2/pipeline (distinct from libsql Hrana WebSocket used by SQLAlchemy)."""
    host = turso_host_from_url(database_url)
    if not host or host == "unknown":
        return False, "invalid_turso_host"
    payload = json.dumps({"requests": [{"type": "execute", "stmt": {"sql": "SELECT 1"}}]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://{host}/v2/pipeline",
        data=payload,
        headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200, None
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def create_ltm_engine() -> tuple[Engine, EngineConfig]:
    cfg = build_engine_config()
    eng = create_engine(
        cfg.url,
        connect_args=cfg.connect_args,
        pool_pre_ping=True,
        future=True,
    )
    return eng, cfg
