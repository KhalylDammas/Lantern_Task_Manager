"""Local Turso replica via pyturso sync when Hrana WebSocket is unavailable."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from ltm.config.env_loader import repo_root
from ltm.storage.engine_config import TursoSyncConfig, normalize_turso_url

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def default_local_replica_path() -> Path:
    explicit = (os.environ.get("TURSO_LOCAL_DB_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    if os.environ.get("WEBSITE_SITE_NAME"):
        return Path("/home/site/data/ltm-replica.db")
    return repo_root() / ".ltm" / "ltm-replica.db"


def pull_replica(cfg: TursoSyncConfig) -> None:
    path = Path(cfg.local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import turso.sync

    with _lock:
        conn = turso.sync.connect(str(path), remote_url=cfg.remote_url, auth_token=cfg.auth_token)
        try:
            conn.pull()
        finally:
            conn.close()
    logger.info("Turso replica pulled to %s", path)


def push_replica(cfg: TursoSyncConfig) -> None:
    import turso.sync

    with _lock:
        conn = turso.sync.connect(cfg.local_path, remote_url=cfg.remote_url, auth_token=cfg.auth_token)
        try:
            conn.push()
        finally:
            conn.close()
    logger.debug("Turso replica pushed from %s", cfg.local_path)
