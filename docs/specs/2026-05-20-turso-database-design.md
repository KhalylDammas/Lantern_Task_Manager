# Turso database (C06 interim) — design spec

**Status:** Implemented (2026-06-10) — pending owner review for queue sign-off  
**Queue:** [LTM_CRITICAL_WORK_QUEUE.md](../LTM_CRITICAL_WORK_QUEUE.md) item #8  
**Spec written:** 2026-05-20 · **Implemented:** 2026-06-10

**Implementation notes (2026-06-10):**

- Dialect ships as the PyPI package **`sqlalchemy-libsql`** (with `libsql`) — not vendored `dialect.py`. Remote URL form: `sqlite+libsql://<host>?secure=true` + `connect_args={"auth_token": …}` per [Turso SQLAlchemy docs](https://docs.turso.tech/sdk/python/orm/sqlalchemy).
- Shared resolution lives in `src/ltm/storage/engine_config.py`; `db.py` and `alembic/env.py` both consume it. No local-file fallback remains; missing config fails fast.
- `create_all()` now runs only for in-memory test databases; deployed schema is Alembic-only.
- Verified locally: `alembic upgrade head` + full `TaskRepository` round-trip through the `sqlite+libsql` dialect. Remote verification against Turso Cloud runs via `tests/test_turso_integration.py` (gated on `TURSO_*` env vars).
- Deploy runbook: [../runbooks/turso-bootstrap.md](../runbooks/turso-bootstrap.md).

## Goal

Use **Turso Cloud** as the **operational** primary transactional store for LTM (tasks, audit trail, idempotency, conversation bindings) until **Azure SQL Database** budget is approved. All environments (local dev, shared dev, Azure App Service bot, Azure Functions timers) connect **remote-only** to the same Turso database — no local replica files, no `pyturso` sync, no embedded replicas.

Preserve the existing **SQLAlchemy ORM + repository** layer; change only connection/bootstrap and dependencies.

## Decisions (2026-05-20)

| Topic | Choice |
|-------|--------|
| **Connection mode** | **Remote-only everywhere** — `libsql` over HTTP to Turso Cloud ([Remote Access](https://docs.turso.tech/sdk/python/quickstart)) |
| **Azure SQL** | **Keep as the documented target architecture** and retain ODBC/`pyodbc` code paths for when cost approval lands; Turso is **interim operational**, not a permanent stack rewrite |
| **Python package** | **`libsql`** (not `pyturso`) — official SQLAlchemy dialect via `sqlite+libsql://` ([libsql-python SQLAlchemy example](https://github.com/tursodatabase/libsql-python/tree/main/examples/sqlalchemy)) |
| **ORM / repositories** | **Keep** — `orm.py`, `repository.py`, `conversation_bindings.py`, `session_scope()` unchanged |
| **Schema management** | **Alembic** as source of truth in non-test environments; stop relying on `create_all()` at startup for deployed environments |
| **Unit tests** | **Keep in-memory SQLite** (`sqlite+pysqlite:///:memory:`) — no Turso creds required in CI |

## Non-goals (this unit)

- `pyturso` / `turso.sync` local-first sync ([quickstart — Sync](https://docs.turso.tech/sdk/python/quickstart))
- `libsql` embedded replicas or local replica files ([reference — Embedded Replicas](https://docs.turso.tech/sdk/python/reference))
- Removing Azure SQL connection support from `db.py` / settings
- Migrating off SQLAlchemy to raw `libsql` SQL
- Cosmos DB scale-up path changes
- Data migration from existing `ltm_local.db` files (manual export/import only if needed)

## Architecture context

```text
Teams bot (App Service C02) ──┐
                                ├── remote libsql ──► Turso Cloud (C06 interim)
Functions timers (C12) ───────┘

Future (when Azure SQL approved):
  same SQLAlchemy layer ──► Azure SQL via pyodbc (existing path)
```

**Why remote-only for Functions:** Azure Functions Consumption has no durable local filesystem; Turso documents remote `libsql` for stateless/serverless workloads ([quickstart — Remote Access](https://docs.turso.tech/sdk/python/quickstart)).

**Why `libsql` not `pyturso`:** LTM is built on SQLAlchemy 2.x. Turso’s SQLAlchemy integration is via the `libsql` package and `sqlite+libsql://` dialect ([examples/sqlalchemy](https://github.com/tursodatabase/libsql-python/tree/main/examples/sqlalchemy)). `pyturso` is recommended for new local-first apps but does not replace SQLAlchemy in this codebase without a large rewrite.

## Current code (baseline — not yet updated)

| File | Today |
|------|--------|
| `src/ltm/storage/db.py` | `DATABASE_URL` → `AZURE_SQL_ODBC_CONNECTION_STRING` → fallback `sqlite+pysqlite` file |
| `src/ltm/storage/alembic/env.py` | Same resolution order (duplicated) |
| `src/ltm/config/settings.py` | `azure_sql_odbc_connection_string` |
| `src/requirements.txt`, `functions/requirements.txt` | `SQLAlchemy`, `pyodbc`, `alembic` |
| Tests | In-memory SQLite via `tests/conftest.py` |

## Target connection resolution (after implementation)

Priority order in `_build_engine_url()` (single shared helper used by Alembic):

1. **`DATABASE_URL`** — explicit override (tests, CI, advanced setups)
2. **`TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN`** — interim operational default when both set
3. **`AZURE_SQL_ODBC_CONNECTION_STRING`** — target architecture when budget approved
4. **Local file SQLite** — **remove** as runtime fallback once Turso is wired (tests keep `:memory:` via `DATABASE_URL` in `conftest.py`)

Credentials live in `env/.env.*.user` / Key Vault — never committed.

### Environment variables (interim)

| Variable | Required when | Notes |
|----------|---------------|-------|
| `TURSO_DATABASE_URL` | Using Turso | Turso Cloud database URL ([quickstart](https://docs.turso.tech/sdk/python/quickstart)) |
| `TURSO_AUTH_TOKEN` | Using Turso | Database auth token; rotate via Turso CLI / platform API |
| `DATABASE_URL` | Optional | Full SQLAlchemy URL override (e.g. `sqlite+libsql://…` for dialect spike) |
| `AZURE_SQL_ODBC_CONNECTION_STRING` | Future / dual-run | Unchanged; activates when set and Turso vars absent (exact precedence TBD in implementation plan) |

## What to keep vs change (implementation checklist)

### Keep

- `src/ltm/storage/orm.py` — SQLite-compatible schema
- `src/ltm/storage/repository.py`, `conversation_bindings.py`
- `session_scope()` contract
- Alembic migration `20260505_01_initial_schema.py`
- `pyodbc` + Azure SQL path in code (dormant until ODBC string provided)
- Test in-memory SQLite pattern

### Change (planned)

- `db.py` — Turso URL builder; register `libsql` SQLAlchemy dialect; consolidate URL logic
- `alembic/env.py` — import shared URL helper
- `settings.py` — optional typed fields for Turso vars
- `requirements.txt`, `functions/requirements.txt` — add `libsql`; vendor or package SQLAlchemy dialect from [libsql-python/examples/sqlalchemy/dialect.py](https://github.com/tursodatabase/libsql-python/blob/main/examples/sqlalchemy/dialect.py)
- `docs/LTM_LOCAL_SETUP.md` — Turso setup; deprecate `ltm_local.db` runtime path
- Deploy runbook — `alembic upgrade head` against Turso before/at deploy

### Remove (after Turso verified)

- `src/ltm_local.db` runtime fallback in `db.py`
- `create_all()` on engine init for non-test environments (Alembic only)

## Schema and compatibility

Existing Alembic migration uses SQLite-compatible DDL (JSON columns, string PKs). Turso/libSQL supports this shape; **verify with one integration test against real Turso** during implementation (not assumed).

Hot path: `TaskCounter.next_sequence()` read-modify-write — acceptable at ~25-user scale; concurrency test during implementation.

## Backup and DR (interim)

While on Turso: use Turso platform features (e.g. [point-in-time recovery](https://docs.turso.tech/features/point-in-time-recovery), branching) per org policy. Azure SQL PITR (**C17**) applies when migrating to the approved Azure SQL tier.

## Azure SQL migration path (future)

When budget approval lands:

1. Provision Azure SQL per **C06** in [LTA_COMPONENT_TECH_STACK.md](../LTA_COMPONENT_TECH_STACK.md)
2. Run Alembic migrations against Azure SQL (may require dialect-specific migration review)
3. Export/import or logical replication from Turso → Azure SQL (procedure TBD)
4. Switch connection precedence to ODBC primary; decommission Turso or keep as dev/staging

Code retains both paths so this is configuration + migration, not a rewrite.

## Implementation phases (next session — plan only)

1. **Spike** — `libsql` + SQLAlchemy dialect connects to dev Turso; run existing migration
2. **Wire** — `db.py`, settings, env examples, both app and Functions requirements
3. **Bootstrap** — Alembic-only schema in deployed envs; document deploy step
4. **Test** — repository tests unchanged; add optional integration test gated on Turso env vars
5. **Docs** — confirm satellite docs match deployed reality

## References

- [Turso Python quickstart](https://docs.turso.tech/sdk/python/quickstart)
- [Turso Python reference](https://docs.turso.tech/sdk/python/reference)
- [libsql-python examples](https://github.com/tursodatabase/libsql-python/tree/main/examples)
- [LTA_COMPONENT_TECH_STACK.md](../LTA_COMPONENT_TECH_STACK.md) **C06**
- [LTA_SYSTEM_DECISIONS.md](../LTA_SYSTEM_DECISIONS.md) §7
