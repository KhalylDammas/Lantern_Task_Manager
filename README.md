# Lantern Task Manager

Lantern Task Manager (LTM) is a Microsoft Teams agent for creating, assigning, tracking, closing, and verifying operational tasks. It combines natural-language capture with guarded tools, Adaptive Cards, Microsoft Graph directory lookup, Dynamics 365 read-only context, persistent task storage, and proactive notifications.

This workspace was reconstructed from the latest salvaged application source and the last known Git repository. The restored `src/` matches the salvaged source bundle; the older repository supplied the compatible Agents Toolkit project, tests, infrastructure, scripts, CI, and documentation.

## What is restored

- Teams personal, group-chat, and channel message handling
- Natural-language and manual-form task capture
- Assignee mention resolution and disambiguation
- Assignment authorization and department policy
- Task acknowledgement, completion, verification, rejection, resume, and cancellation workflows
- Groq primary/fallback models with rate limits, retries, circuit breaking, memory trimming, and daily usage accounting
- Microsoft Graph lookup and Teams activity/proactive bot notifications
- Dynamics 365 guarded read-only façade
- Turso, Azure SQL, and explicit SQLAlchemy database configuration
- Alembic migrations through notification delivery logging
- Health, legal, and protected scheduled-job HTTP endpoints
- Microsoft 365 Agents Toolkit local, Playground, Azure provision, deploy, and package configuration

The recovered `ltm_local.db` was intentionally not copied into the application. It remains in the external recovery bundle and is treated as runtime data, not deployable source.

## Runtime

Use Python 3.12. The Azure App Service configuration and CI both target 3.12. Python 3.14 is not supported by the current libSQL dependency stack.

```bash
/opt/cpython/3.12.13/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r src/requirements.txt
```

The restored application uses the Microsoft Teams SDK v2 packages that its source was built against. Their compatible versions are pinned in `src/requirements.txt` to prevent an alpha-package upgrade from silently breaking the agent.

## Secrets to fill

Recovered secret values were not copied. Fill the empty keys in `env/.env.local.user` for local F5 debugging and in `env/.env.dev.user` for Azure provisioning/deployment:

```dotenv
SECRET_BOT_PASSWORD=
SECRET_GROQ_API_KEY=
SECRET_OPENAI_API_KEY=
SECRET_TURSO_DATABASE_URL=
SECRET_TURSO_AUTH_TOKEN=
SECRET_D365_CLIENT_SECRET=
SECRET_LTM_CRON_SECRET=
```

Groq is the recovered primary provider, so `SECRET_GROQ_API_KEY` is required. `SECRET_OPENAI_API_KEY` is optional unless the provider is changed to OpenAI/Azure OpenAI. See `env/.env.dev.example` for the canonical blank template.

Non-secret recovered settings—including model IDs, notification flags, verifier mode, Teams IDs, and D365 identifiers—are in `env/.env.dev`.

## Local Teams debugging

1. Install the Microsoft 365 Agents Toolkit VS Code extension and sign in.
2. Select the `.venv` Python interpreter.
3. Fill `env/.env.local.user`.
4. Press F5 and choose **Debug in Teams (Edge)**, **Debug in Teams (Chrome)**, or **Debug in Teams (Desktop)**.

The local Toolkit lifecycle creates/reuses the bot registration, starts the tunnel, packages the Teams app, and maps `SECRET_*` inputs to the runtime variable names consumed by LTM.

For Playground, fill `env/.env.playground.user`; Playground uses an in-memory SQLite database and skips bot authentication.

## Database schema

For local automated tests, the schema is created automatically in memory. Operational databases are migrated with Alembic:

```bash
cd src
TURSO_DATABASE_URL='libsql://…' TURSO_AUTH_TOKEN='…' ../.venv/bin/alembic upgrade head
```

Connection precedence is:

1. `DATABASE_URL`
2. `TURSO_DATABASE_URL` plus `TURSO_AUTH_TOKEN`
3. `AZURE_SQL_ODBC_CONNECTION_STRING`

When direct Turso Hrana connectivity is unavailable but the HTTP pipeline is reachable, LTM uses a synchronized local replica under `.ltm/` locally or `/home/site/data/` on Azure.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m compileall -q src tests
```

Credential-free route smoke test:

```bash
PYTHONPATH=src DATABASE_URL='sqlite+pysqlite:///:memory:' BOT_SKIP_AUTH=true \
  .venv/bin/python src/app.py
```

The app exposes:

- `GET /health`
- `GET /`, `/privacy`, and `/terms`
- `POST /internal/cron/overdue`
- `POST /internal/cron/daily-summary`
- `POST /internal/cron/notification-retry`

Cron routes require `X-LTM-Cron-Secret` to match `LTM_CRON_SECRET`.

## Azure deployment

1. Fill `env/.env.dev.user`.
2. Complete the Azure subscription/resource-group values in `env/.env.dev` if provisioning new infrastructure.
3. Run **Provision** from Agents Toolkit.
4. Apply Alembic migrations to the operational database.
5. Run **Deploy** and verify `/health` before installing or updating the Teams app.

Provisioning stores bot, LLM, Turso, D365, and cron secrets in Azure Key Vault and exposes Key Vault references to App Service. The Teams manifest uses the deployed bot domain for the legal URLs and valid-domain declaration.

More detail is available in `docs/LTM_LOCAL_SETUP.md`, `docs/LTM_SYSTEM_SPEC.md`, and the runbooks under `docs/runbooks/`.
