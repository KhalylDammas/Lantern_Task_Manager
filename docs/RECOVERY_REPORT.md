# Recovery report — 2026-07-18

## Sources

- Latest application source: `/home/khalyli/Projects/recover_ltm/source_files`
- Last known repository: `/home/khalyli/Projects/recover_ltm/LTM_Teams_Agent_OLD`
- Latest App Service settings export: `/home/khalyli/Projects/recover_ltm/ltm_env.json`

The latest bundle is authoritative for application behavior. The old repository supplied the compatible Microsoft 365 Agents Toolkit scaffold, tests, documentation, scripts, CI, app package, and infrastructure baseline.

## Recovery decisions

- Restored the complete latest source tree under `src/`.
- Excluded `ltm_local.db`; it remains external recovery data and is not deployable source.
- Removed the incompatible starter `src/agent.py` from the fresh template.
- Removed the legacy Azure Functions scheduler because the latest source implements protected App Service cron routes.
- Removed the dormant managed-identity Graph role module because this recovered deployment uses the existing single-tenant bot application with client credentials.
- Retained this workspace's Agents Toolkit `projectId`.
- Restored the recovered non-secret Teams, LLM, notification, verifier, and D365 settings.
- Added every recovered secret category as an empty `SECRET_*` placeholder; no secret value was copied.
- Expanded Bicep/Key Vault/App Service wiring for Groq, D365, Turso, bot authentication, Teams notifications, and cron authentication.
- Pinned the Microsoft Teams SDK packages to the versions validated during recovery.

## Required secret inputs

Fill these in `env/.env.local.user` and/or `env/.env.dev.user` as appropriate:

- `SECRET_BOT_PASSWORD`
- `SECRET_GROQ_API_KEY`
- `SECRET_OPENAI_API_KEY` (optional with the recovered Groq configuration)
- `SECRET_TURSO_DATABASE_URL`
- `SECRET_TURSO_AUTH_TOKEN`
- `SECRET_D365_CLIENT_SECRET`
- `SECRET_LTM_CRON_SECRET`

## Validation evidence

- Python 3.12 dependency installation: passed
- `pip check`: passed
- Python compile check for `src/` and `tests/`: passed
- Test suite: **65 passed, 1 credential-gated Turso integration test skipped**
- Application import and route smoke test: passed
- Legal pages: HTTP 200
- In-memory `/health`: HTTP 200, status `ok`
- Cron route without secret: HTTP 403
- Teams manifest and ARM parameters JSON parsing: passed
- Agents Toolkit and CI YAML parsing: passed
- Azure Bicep compilation: passed with no diagnostics
- Alembic upgrade from an empty database through `20260630_01`: passed

## Known upgrade item

The restored source uses Microsoft Teams SDK v2 AI packages that now emit deprecation warnings in favor of Microsoft Agent Framework. They remain pinned because changing frameworks during recovery would alter behavior. Framework migration should be a separate enhancement with Teams end-to-end regression testing.
