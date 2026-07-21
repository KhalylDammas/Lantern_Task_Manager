# Local development setup (LTM)

## Microsoft 365 Agents Toolkit — version control

Toolkit-managed files follow [TeamsFx environments](https://learn.microsoft.com/en-us/microsoftteams/platform/toolkit/teamsfx-multi-env) and the [.gitignore in official samples](https://github.com/OfficeDev/microsoft-365-agents-toolkit-samples/blob/dev/command-bot-with-sso/.gitignore).

| Track in git                                                               | Do not track (gitignored)                                   |
| -------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `m365agents.yml` — shared lifecycle                                        | `env/.env.*.user` — secrets (`SECRET_*`)                    |
| `m365agents.local.yml` — local debug overrides                             | `env/.env.local` — per-machine local env                    |
| `m365agents.playground.yml` — Playground overrides                         | `env/.env.playground` — Playground env                      |
| `env/.env.dev` — shared **dev** env (resource IDs, app IDs from provision) | `.localConfigs`, root `.env` — runtime exports from Toolkit |

**Commit** `env/.env.dev` for a shared remote dev environment so collaborators reuse the same provisioned resource IDs. Put passwords and API keys only in `env/.env.dev.user` (and `env/.env.local.user` for F5), never in the committed `.env.dev` file.

After clone, collaborators typically:

1. Pull the repo (gets `m365agents*.yml` and `env/.env.dev`).
2. Create `env/.env.dev.user` locally with `SECRET_*` values.
3. Sign in via Agents Toolkit and use **Provision** / **Deploy** for `dev`, or **F5** for `local` (Toolkit writes `env/.env.local`).

See also [Collaborate on TeamsFx](https://learn.microsoft.com/en-us/microsoftteams/platform/toolkit/teamsfx-collaboration).

## Database (C06)

### Target vs interim (implemented 2026-06-10, Unit #8)

| Role | Store | Notes |
|------|-------|-------|
| **Target architecture** | Azure SQL Database | Preferred when budget is approved; ODBC path remains in code |
| **Interim operational** | **Turso Cloud** | Direct Hrana connection with a synchronized local replica fallback when WebSockets are unavailable |

Design spec: [specs/2026-05-20-turso-database-design.md](specs/2026-05-20-turso-database-design.md).

Connection precedence (`src/ltm/storage/engine_config.py`, shared by runtime and Alembic):

1. `DATABASE_URL` — explicit SQLAlchemy URL override (tests use `sqlite+pysqlite:///:memory:`)
2. `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` — Turso remote via `sqlalchemy-libsql`
3. `AZURE_SQL_ODBC_CONNECTION_STRING` — Azure SQL via `pyodbc`
4. Nothing set → the app **fails fast** with a clear error (`src/ltm_local.db` is never created implicitly)

For Turso, LTM first probes the direct Hrana connection. If that fails but Turso's HTTP pipeline is reachable, `pyturso` pulls a synchronized replica to `.ltm/ltm-replica.db` locally or `/home/site/data/ltm-replica.db` on Azure and pushes committed changes back to Turso. `TURSO_FORCE_SYNC=true` forces this path; `TURSO_LOCAL_DB_PATH` overrides the local replica location.

### Turso credentials

Local dev (F5): fill these Toolkit inputs in `env/.env.local.user` (never commit):

- `SECRET_TURSO_DATABASE_URL` — Turso Cloud database URL, e.g. `libsql://<db>-<org>.turso.io`
- `SECRET_TURSO_AUTH_TOKEN` — database auth token

Azure provision (Toolkit `dev`): add to `env/.env.dev.user`:

- `SECRET_TURSO_DATABASE_URL`
- `SECRET_TURSO_AUTH_TOKEN`

`infra/azure.bicep` stores these in Key Vault (`ltm-turso-database-url`, `ltm-turso-auth-token`) and exposes them as `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` App Service settings. See `env/.env.dev.example` for the complete blank secret template.

### Schema bootstrap (Alembic)

Schema is owned by Alembic — the app only auto-creates tables for in-memory test databases. Run once per environment (and after every new migration):

```bash
cd src
TURSO_DATABASE_URL=libsql://<db>-<org>.turso.io TURSO_AUTH_TOKEN=<token> alembic upgrade head
```

**Platform note:** use Python 3.12. `sqlalchemy-libsql` is experimental and supports Linux/macOS; on native Windows, use WSL or point `DATABASE_URL` at another backend.

Deploy runbook: [runbooks/turso-bootstrap.md](runbooks/turso-bootstrap.md).

## Microsoft Graph auth (C03)

Graph and proactive Bot Connector tokens come from `src/ltm/auth/tokens.py`:

- **Azure** — client credentials for the existing Entra bot app registration (`CLIENT_ID` / `CLIENT_SECRET` / `TENANT_ID`; `BOT_TYPE` empty). Put the client secret in `env/.env.dev.user` as `SECRET_BOT_PASSWORD`.
- **Local F5** — client credentials (`CLIENT_ID` / `CLIENT_SECRET` / `TENANT_ID` written by the Toolkit).

Verify with `python scripts/verify_graph_access.py` or `GET /health` on the running app. Full runbook: [runbooks/graph-azure-msi.md](runbooks/graph-azure-msi.md).

## Assignment directory seeding

Authorization reads `src/config/assignment_directory.json`, built from **`src/config/assignment_directory.csv`**.

1. Edit the CSV: `include=Y`, `department_code` (`FIN|PROC|OP|HR|IT|CEO`), optional `manager_entra_id`. Entra `department` is empty for most users — set `department_code` manually. Users in `CEO` may assign to anyone whose `manager_entra_id` is their Entra id (see `assignment_policy.json`).
2. With `az login`, refresh Graph fields and rebuild:

```bash
python scripts/seed_assignment_directory.py enrich --include
python scripts/seed_assignment_directory.py build
```

3. Export internal users to pick from (regenerable, not used at runtime):

```bash
python scripts/seed_assignment_directory.py export-candidates
```

Copy rows from `assignment_directory.candidates.csv` into `assignment_directory.csv` as you onboard staff (~25). Without your Entra id in the built JSON, task create/confirm is denied.
