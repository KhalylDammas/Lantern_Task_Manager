# Runbook — Microsoft Graph auth on Azure (C03)

**Scope:** How the deployed bot authenticates to Microsoft Graph and the proactive Bot
Connector, what to configure in Entra, and how to verify a deployment. Token logic lives in
`src/ltm/auth/tokens.py` — the single source of truth for both auth modes.

## Auth modes

| Mode | Where | How it is selected | Credentials |
|------|-------|--------------------|-------------|
| `client_secret` | Azure App Service / Local F5 / Playground | `CLIENT_SECRET` present, `BOT_TYPE` empty | Existing Entra bot app registration (`CLIENT_ID` / `CLIENT_SECRET` / `TENANT_ID`) |
| `msi` | Legacy/optional Azure App Service / Functions | `BOT_TYPE=UserAssignedMsi` app setting | UserAssigned managed identity (`CLIENT_ID` app setting); **no** `CLIENT_SECRET` |

The bot host never gates Graph on `CLIENT_SECRET` (the old behavior that silently disabled
Graph on Azure). It gates on `graph_configured()`, which accepts either mode.

## Required Entra configuration (one-time)

### Critical: one canonical Azure bot app

| Environment | How the bot app is created | Where Graph permissions must be granted |
|-------------|---------------------------|----------------------------------------|
| **Azure (ARM deploy)** | Existing Entra app registration from `infra/azure.parameters.json` → `botClientId` | That app registration: `fddfdd2c-9747-43bb-9895-58185732923d` |
| **Local F5** | Toolkit `aadApp/create`, unless reused manually | The local `BOT_ID` / `CLIENT_ID` in `env/.env.local` |

If admin consent was granted on a different app than the deployed App Service `CLIENT_ID`,
Graph returns **403 Authorization_RequestDenied** even though “permissions look granted” in
the portal — they are on the wrong registration.

Startup logs now decode the token `roles` claim. If you see `token roles=[]`, permissions are
not on the active `CLIENT_ID` app.

### Required Azure secret

`infra/azure.bicep` stores the existing bot app client secret in Key Vault and exposes it as
`CLIENT_SECRET`. Put the real value in `env/.env.dev.user`:

```bash
SECRET_BOT_PASSWORD=<existing bot app client secret>
```

### Grant on the active bot app

From a machine with `az login` as tenant admin:

```bash
chmod +x scripts/grant_msi_graph_permissions.sh
# Use the CLIENT_ID value from App Service → Configuration (or startup logs)
./scripts/grant_msi_graph_permissions.sh fddfdd2c-9747-43bb-9895-58185732923d
```

Then restart the App Service or wait for the health cache (5 min) and re-check `/health`.

### Manual portal steps

1. Entra ID → **App registrations** → search by the App Service **`CLIENT_ID`**.
2. **API permissions → Add a permission → Microsoft Graph → Application permissions**:
   - `User.Read.All` — required for directory search (`/who`, @mention resolution).
3. **Grant admin consent** for the tenant.

### IaC (future provisions)

`infra/graphRoleAssignment.bicep` can assign `User.Read.All` to a managed identity service
principal during ARM deploy, but it is disabled by default with
`enableGraphRoleAssignment=false` in `infra/azure.parameters.json`. It is not needed for the
current app-registration deployment mode. Enable it only when switching back to MSI and when
the deployer has **Privileged Role Administrator** (or Global Administrator). The module
requires Bicep with the Microsoft Graph extension; Toolkit currently uses `v0.32.4`.

If permissions are granted on a *different* app than `CLIENT_ID`, Graph calls return 403
(`Authorization_RequestDenied`) and the startup probe / `/health` will say so.

## Built-in guardrails

- **Startup probe** — on boot the app calls Graph (`GET /v1.0/users?$top=1`) and logs
  `Startup Graph probe OK: mode=client_secret` or an ERROR with remediation hints. Check the App
  Service log stream right after a deploy.
- **`GET /health`** — returns Graph and database status:

  ```json
  {
    "status": "ok",
    "program": "ltm",
    "graph": {"ok": true, "mode": "client_secret", "detail": "Graph reachable"},
    "database": {"ok": true, "backend": "turso", "detail": "Database reachable"}
  }
  ```

  `graph.ok: false` means degraded mention resolution (HTTP stays 200); an unreachable
  database returns 503. The Graph probe result is cached for 5 minutes.
- **Per-message log field** — every inbound message logs `graph_auth_mode=msi|client_secret|none`
  and `graph_search_enabled=True|False`. `none`/`False` on Azure means misconfiguration.
- **CLI check** — from the repo (locally with `.env` files, or in an App Service SSH session):

  ```bash
  python scripts/verify_graph_access.py
  ```

## Post-deploy verification checklist

1. Log stream shows `Startup Graph probe OK: mode=client_secret`.
2. `curl https://<app>.azurewebsites.net/health` → `graph.ok: true`.
3. In Teams, `/who abdulkhaliq` returns directory results.
4. Send `assign a task to @<name> ... due <date> priority <p>` → log shows
   `graph_search_enabled=True` and `pending_cards=1`, and a confirmation card appears.
5. Click **Confirm** on the card → log shows `Card action outcome: ... verb=confirm_task outcome=created`.
6. `my tasks` lists the created task.

## Known benign log noise

- `GET https://token.botframework.com/api/usertoken/GetToken?...&connectionName=graph → 404`
  — the Teams SDK probing for a Bot Framework **user OAuth connection** named `graph`
  (SSO / delegated tokens). This app uses app-only Graph and does not need it. Configure an
  OAuth connection on the Azure Bot resource only if delegated SSO is added later.
- Task confirmation is by **clicking Confirm on the Adaptive Card**, not by typing
  "confirm" in chat — typed "confirm" goes to the LLM.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `graph.ok: false`, detail mentions `403` / `Authorization_RequestDenied` | Almost always permissions on the **wrong** Entra app. Check startup log for `token roles=[]`. Run `scripts/grant_msi_graph_permissions.sh <CLIENT_ID>` on the active bot app. Must be **Application** permission `User.Read.All`, not Delegated. |
| `graph.ok: false`, detail mentions token acquisition | Check App Service `CLIENT_ID`, `CLIENT_SECRET`, and `TENANT_ID`; verify the secret has not expired. |
| `graph_auth_mode=none` in logs | `CLIENT_SECRET` is missing or empty, or `BOT_TYPE` is set incorrectly — check App Service settings / local `.env` |
| Proactive DMs skipped, log: `Bot Connector auth not configured` | Same root cause as above; Connector tokens use the same module |
