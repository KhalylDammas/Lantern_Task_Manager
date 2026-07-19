"""Database engine and session factory."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy.orm import Session, sessionmaker

from ltm.storage.engine_config import TursoSyncConfig, create_ltm_engine
from ltm.storage.orm import Base

logger = logging.getLogger(__name__)


_engine = None
SessionLocal: Optional[sessionmaker[Session]] = None
_turso_sync: TursoSyncConfig | None = None


def reset_engine() -> None:
    global _engine, SessionLocal, _turso_sync
    if _engine is not None:
        _engine.dispose()
    _engine = None
    SessionLocal = None
    _turso_sync = None


def engine():
    global _engine, SessionLocal, _turso_sync
    if _engine is None:
        _engine, cfg = create_ltm_engine()
        _turso_sync = cfg.turso_sync
        mode = "sync_replica" if cfg.turso_sync else "remote"
        logger.info("Database engine initialized (backend=%s mode=%s)", cfg.backend, mode)
        if cfg.is_memory:
            # Tests only; deployed environments get schema via Alembic.
            Base.metadata.create_all(_engine)
        SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    eng = engine()
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        yield session
        session.commit()
        if _turso_sync is not None:
            from ltm.storage.turso_sync import push_replica

            push_replica(_turso_sync)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
