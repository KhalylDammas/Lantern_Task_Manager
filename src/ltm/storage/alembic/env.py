"""Alembic environment — shared resolution: DATABASE_URL / TURSO_* / AZURE_SQL_ODBC_*."""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

from ltm.storage.engine_config import build_engine_config
from ltm.storage.orm import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    cfg = build_engine_config()
    context.configure(url=cfg.url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = build_engine_config()
    if cfg.turso_sync is not None:
        from ltm.storage.turso_sync import pull_replica, push_replica

        pull_replica(cfg.turso_sync)
    connectable = create_engine(cfg.url, connect_args=cfg.connect_args, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

    if cfg.turso_sync is not None:
        push_replica(cfg.turso_sync)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
