# Runbook — Turso database bootstrap and deploy (C06 interim)

**Scope:** First-time setup and schema upgrades for the Turso Cloud database used by the LTM bot (App Service) and timer Functions. See [../specs/2026-05-20-turso-database-design.md](../specs/2026-05-20-turso-database-design.md).

## 1. Create the database and token (once per environment)

```bash
turso db create ltm-<env>            # e.g. ltm-dev, ltm-prod
turso db show ltm-<env> --url        # → TURSO_DATABASE_URL (libsql://…)
turso db tokens create ltm-<env>     # → TURSO_AUTH_TOKEN
```

Token rotation: `turso db tokens invalidate ltm-<env>` then create a new token and update Key Vault / `.env.local.user`.

## 2. Store secrets

| Where | Keys |
|-------|------|
| `env/.env.dev.user` (Toolkit provision) | `SECRET_TURSO_DATABASE_URL`, `SECRET_TURSO_AUTH_TOKEN` |
| `env/.env.local.user` (local F5) | `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` |
| Key Vault (written by provision) | `ltm-turso-database-url`, `ltm-turso-auth-token` |

## 3. Apply schema (once per environment, and after each new migration)

```bash
cd src
TURSO_DATABASE_URL=libsql://<db>-<org>.turso.io TURSO_AUTH_TOKEN=<token> alembic upgrade head
```

## 4. Provision and deploy

1. Toolkit **Provision** (`dev`) — bicep writes Turso secrets to Key Vault and wires `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` app settings on the App Service and Function App.
2. Toolkit **Deploy** — zip-deploys `src/` (and Functions).
3. Verify: create a task via the bot and confirm the row lands in Turso (`turso db shell ltm-<env> "select task_id, status from ltm_tasks order by created_at desc limit 5"`). No `src/ltm_local.db` file should appear.

## 5. Failure modes

| Symptom | Cause / fix |
|---------|-------------|
| `RuntimeError: No database configured` at startup | None of `DATABASE_URL` / `TURSO_*` / `AZURE_SQL_ODBC_CONNECTION_STRING` resolved — check app settings / `.env.local.user` |
| `no such table: ltm_tasks` | Alembic not run against this database — step 3 |
| Auth errors from libsql | Token expired/invalidated — rotate token, update Key Vault secret, restart app |

## 6. Azure SQL cutover (future)

When Azure SQL budget is approved: run Alembic against Azure SQL, migrate data Turso → SQL, then remove the `TURSO_*` app settings so precedence falls through to `AZURE_SQL_ODBC_CONNECTION_STRING`. Code changes are not required.
