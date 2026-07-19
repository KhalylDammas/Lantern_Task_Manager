# LTA Component Technology Stack

> **Satellite document.** Master program specification: [`LTM_SYSTEM_SPEC.md`](LTM_SYSTEM_SPEC.md) (**LTM** — Lantern Task Manager).

This document specifies **technologies, tools, frameworks, and typical Azure services** chosen (or deferred) **per logical component** `C01`–`C19` from `docs/LTA_ARCHITECTURE_PRECODE.md` §3.

**Scope:** stack only—**not** behavioral requirements (those live in `docs/LTA_TECHNICAL_REQUIREMENTS.md`).

**Conventions:** Python **3.12** unless the Microsoft 365 Agents Toolkit template for your scenario mandates a supported alternative (then record a deviation in `docs/LTA_SYSTEM_DECISIONS.md`). Pin exact package versions in `requirements.txt` or **uv** lockfile at implementation time, not in this document.

---

## Global stack (shared)

| Layer            | Choice                                                                            |
| ---------------- | --------------------------------------------------------------------------------- |
| Language         | **Python 3.12**                                                                   |
| Async I/O        | **asyncio**; HTTP client **httpx** (async)                                        |
| Data validation  | **Pydantic v2**                                                                   |
| Azure identity   | **azure-identity** (`DefaultAzureCredential`, managed identity)                   |
| Secrets / config | **Azure Key Vault** (`azure-keyvault-secrets`); non-secrets in App Settings / env |
| Packaging / env  | **venv** or **uv**; **pip**-compatible installs                                   |

---

## C01 — Microsoft Teams & Adaptive Cards

| Category    | Technology / tool                                                              |
| ----------- | ------------------------------------------------------------------------------ |
| Client      | **Microsoft Teams** (desktop / web / mobile)                                   |
| Card format | **Adaptive Cards** JSON (**schema** version pinned per card set at build time) |
| Rendering   | Host-provided (Teams); no separate renderer in your service                    |

**Notes:** Card payloads are built in app code (Python dict → JSON) or static templates; optional **Designer** for authoring.

---

## C02 — Agent host and HTTP ingress

| Category            | Technology / tool                                                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Delivery / project  | **Microsoft 365 Agents Toolkit** (scaffold, config, deploy tasks)                                                                  |
| Bot runtime         | **Bot Framework SDK for Python** (or toolkit-wrapped equivalent), **aiohttp** / **Starlette**-based adapter as provided by toolkit |
| Web app (typical)   | **Azure App Service**, **Linux**, runtime **Python 3.12**                                                                          |
| WSGI/ASGI server    | **uvicorn** (or **gunicorn** + uvicorn workers if toolkit recommends)                                                              |
| Optional direct API | **FastAPI** only if the toolkit layout keeps a separate webhook/API process (align with single host if possible)                   |

**Notes:** Azure **Bot Service** (single-tenant or multi-tenant per IT) fronts Teams → your messaging endpoint.

---

## C03 — Microsoft Graph integration

| Category | Technology / tool                                                                                                                          |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| API      | **Microsoft Graph** REST `v1.0`                                                                                                            |
| Auth     | **MSAL Python** (`msal`, confidential client for app-only flows used by timers / proactive; delegated where required)                      |
| HTTP     | **httpx** (async) or official **Graph SDK for Python** (`msgraph-sdk`)—pick one per repo convention; avoid duplicating both without reason |


**Notes:** Exact **Application / delegated permissions** are tenant-specific; list them in `docs/runbooks/` when provisioned.

---

## C04 — Identity binding and mentions

| Category           | Technology / tool                                                                            |
| ------------------ | -------------------------------------------------------------------------------------------- |
| Activity parsing   | **Bot Framework** activity schema (`ChannelAccount`, `Mention`, `conversation` / `from` ids) |
| Directory backfill | **C03** (Graph `GET /users` or `$filter` by UPN / mail)                                      |

**Notes:** Persist **Entra object id** (and tenant id if multi-tenant ever considered) as canonical user key.

---

## C05 — Task and workflow domain

| Category              | Technology / tool                                                                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Application structure | Plain Python **packages** (e.g. `app/tasks`, `app/workflow`)                                                                                      |
| Validation & DTOs     | **Pydantic v2** models                                                                                                                            |
| Rules config          | **JSON** or **YAML** files (`task_catalogue`, `manager_map`, `escalation_rules`) loaded at startup or on change                                   |
| State machine         | Idiomatic Python **enums** + explicit transition functions, or a small library (e.g. **transitions**)—choose one; avoid heavy BPM engines for MVP |

---

## C06 — Primary transactional store

| Category                           | Technology / tool                                                                                                                                                                                                                                                                                                                 |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Target architecture (MVP)**      | **Azure SQL Database** (e.g. **General Purpose** serverless or smallest **DTU/vCore** tier that meets policy—size at implementation). **Preferred** when budget is approved.                                                                                                                                                      |
| **Interim operational (2026-05-20)** | **Turso Cloud** (libSQL) — **remote-only** access via **`libsql`** Python package + **SQLAlchemy 2.x** (`sqlite+libsql://` dialect). Used until Azure SQL cost approval. See [specs/2026-05-20-turso-database-design.md](specs/2026-05-20-turso-database-design.md).                                                          |
| **Application access (runtime)**   | **SQLAlchemy 2.x** (sync sessions today; async engine where used from async code). **Turso interim:** `libsql` remote connect. **Azure SQL target:** `**pyodbc**` + **Microsoft ODBC Driver 18 for SQL Server**; authentication via **SQL login** (secret in Key Vault) and/or **Entra-only** auth using `**azure-identity**` token with ODBC token plugin / driver settings per Microsoft guidance |
| **Resource management (optional)** | `**azure-mgmt-sql`** — Azure Resource Manager SDK for **provisioning or automating** servers/databases (management plane). **Not** used for task CRUD at runtime. Prefer **Bicep**/**Terraform** for IaC if that is the org standard. Turso provisioning via [Turso CLI / Platform API](https://docs.turso.tech/api-reference/introduction). |
| **Scale-up option**                | **Azure Cosmos DB for NoSQL** (Core SQL API) — SDK `**azure-cosmos`** (e.g. hybrid or migration path if document scale/query needs exceed SQL MVP)                                                                                                                                                                                |
| **Schema evolution**               | **Alembic** (or toolkit-aligned migration runner) for versioned schema; backward-compatible migrations                                                                                                                                                                                                                            |

**Notes:** Backup / PITR per **C17** (Azure SQL when adopted; Turso platform features while interim). JSON substructures (e.g. `d365References`, audit snippets) **May** live in **JSON**-typed columns or normalized child tables—implementation choice. **Do not** use Turso embedded replicas or `pyturso` sync for LTM — remote-only everywhere ([design spec](specs/2026-05-20-turso-database-design.md)).

---

## C07 — D365 read and lookup facade

| Category   | Technology / tool                                                              |
| ---------- | ------------------------------------------------------------------------------ |
| HTTP       | **httpx** (async)                                                              |
| Auth       | **MSAL** client credentials → bearer token for D365 resource                   |
| API shape  | **OData v4** against F&O **data entities**; URLs built only inside this module |
| Resilience | **tenacity** (or custom async retry) for **429** / 5xx with jittered backoff   |
| Parsing    | **Pydantic** (or **msgspec**) for response shaping                             |

**Notes:** Entity names from validated `$metadata` per D365 admin; no OData surface exposed raw to the LLM.

---

## C08 — Secrets and configuration

| Category      | Technology / tool                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Secrets store | **Azure Key Vault**                                                                                                      |
| Runtime read  | **azure-keyvault-secrets** + **azure-identity** (managed identity on App Service / Functions)                            |
| Non-secrets   | App Service / Function **Application settings**, **Azure App Configuration** (optional, if you want feature flags later) |

---

## C09 — LLM gateway

| Category                 | Technology / tool                                                                                                                                                                                                                                                                                                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Primary                  | **Anthropic** official SDK (`**anthropic`**) — async client if available in pinned version                                                                                                                                                                                                                                                  |
| Fallback                 | **OpenAI Python SDK** (`openai`) against **Azure OpenAI** (Azure base URL + API version + deployment id)                                                                                                                                                                                                                                    |
| Testing / dev throughput | **Groq** via **OpenAI-compatible HTTP API** — same `**openai`** client with `base_url` set to Groq’s OpenAI-compatible endpoint (e.g. `https://api.groq.com/openai/v1`) and `**GROQ_API_KEY**`; use only in non-prod or behind an explicit `**LLM_PROVIDER**` (or similar) config flag so production defaults stay Anthropic / Azure OpenAI |
| Config                   | Env / Key Vault: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL_ID`, `AZURE_OPENAI_*`, `GROQ_API_KEY`, Groq model id, timeouts, breaker thresholds                                                                                                                                                                                                   |
| Tool calling             | Map model tool invocations to **internal Python callables** (which call **C07** / **C05**), not free-form HTTP                                                                                                                                                                                                                              |

**Notes:** Circuit breaker: small custom state machine or `**pybreaker`**-style pattern; keep dependency count low. Treat **Groq** as an **optional third route** for speed/cost in test environments, not a silent production fallback unless explicitly approved.

---

## C10 — Redaction and sensitivity gate


| Category          | Technology / tool                                                                                                           |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Policy            | **YAML** or **JSON** file in repo (or App Config) defining classes of PII/finance fields and placeholder tokens             |
| Engine            | Pure Python (regex + allowlist/denylist, or structured field path stripping on Pydantic models before serialization to LLM) |
| Privileged access | **Microsoft Entra ID** **App roles** on the bot’s enterprise application; check in admin/support endpoints only             |


---

## C11 — Observability and FinOps signals *(optional)*

**Positioning:** **Optional**—not a structural building block of the bot. MVP **Must** still be operable using **host-native logs** (App Service / Functions **Log stream** and diagnostic settings) without deploying Application Insights.

| Category           | Technology / tool                                                                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| When enabled       | **Azure Monitor Application Insights**                                                                                                                                   |
| Python integration | `**azure-monitor-opentelemetry`** exporter and **OpenTelemetry** API, or `**opencensus-ext-azure`** (legacy; prefer current Microsoft Python guidance when you scaffold) |
| Structured logs    | `**structlog**` or stdlib `**logging**` JSON formatter (valuable **with or without** App Insights)                                                                       |
| Custom events      | App Insights **TrackEvent** / OTel metrics for NL vs form paths (only when **C11** is on)                                                                                |

---

## C12 — Scheduled jobs

| Category   | Technology / tool                                                              |
| ---------- | ------------------------------------------------------------------------------ |
| Runtime    | **Azure Functions** v4, **Python** programming model **v2**                    |
| Plan       | **Consumption** (Y1) or **Flex Consumption** per cost/perf review              |
| Triggers   | **Timer trigger** (`schedule` in `function.json` / Python decorator per model) |
| Local test | **Azure Functions Core Tools**                                                 |

**Notes:** Same **managed identity** and Key Vault access pattern as **C02** where possible.

---

## C13 — Optional reliability queue

| Category | Technology / tool                                                                   |
| -------- | ----------------------------------------------------------------------------------- |
| Queue    | **Azure Queue Storage**                                                             |
| SDK      | `**azure-storage-queue`**                                                           |
| Consumer | Second Function with **queue trigger**, or retry loop in **C12** after proving need |

---

## C14 — Structured task capture (forms)

| Category | Technology / tool                                                                       |
| -------- | --------------------------------------------------------------------------------------- |
| UI       | **Adaptive Cards** (`Input.Text`, `Input.Date`, `Input.ChoiceSet`, `Action.Submit`)     |
| Optional | Teams **Task Modules** (deep link / `task/fetch`) if UX needs a modal—toolkit-dependent |

**Notes:** Submit payloads merge into the same **Pydantic** validators as **C05** NL-extracted drafts.

---

## C15 — CI/CD and environments

| Category          | Technology / tool                                                                                                |
| ----------------- | ---------------------------------------------------------------------------------------------------------------- |
| Pipeline          | **GitHub Actions** (`ubuntu-latest` runners typical)                                                             |
| IaC (recommended) | **Bicep** or **Terraform**—match org standard                                                                    |
| Deploy            | **Agents Toolkit** CLI / GitHub Action; **Azure CLI** (`az`) for App Service / Function deploy                   |
| Secrets in CI     | **GitHub Environments** + **OIDC federated credentials** to Azure (no long-lived SP password in GH if avoidable) |

---

## C16 — Local developer workstation

| Category | Technology / tool                                                       |
| -------- | ----------------------------------------------------------------------- |
| IDE      | **Visual Studio Code** + **Teams Toolkit** / Agents Toolkit extension   |
| Tunnel   | **Dev Tunnels** (or toolkit default) to expose local messaging endpoint |
| Runtime  | **Python 3.12** local venv; **Azure Functions Core Tools** for **C12**  |

---

## C17 — Backup and DR

| Category         | Technology / tool                                                                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Azure SQL (target) | **Automated backups** / **PITR** per SKU; optional **long-term retention** (LTR) to Azure Blob per policy; geo-redundant **storage** for backup files when enabled |
| Turso (interim)  | Turso Cloud **point-in-time recovery**, branching, and platform backups per [Turso docs](https://docs.turso.tech/features/point-in-time-recovery) and org policy |
| Cosmos (if used) | **Continuous backup** / PITR per Cosmos feature set at adoption time                                                                                               |
| Export           | Scheduled Function + **Blob Storage** for logical exports (BACPAC/CSV/JSON—format TBD) optional                                                                    |

---

## C18 — Operational governance hooks

| Category    | Technology / tool                                                                                   |
| ----------- | --------------------------------------------------------------------------------------------------- |
| Repo        | **Git** + **GitHub** (or Azure DevOps if org mandates)                                              |
| Cost alerts | **Azure Cost Management** budgets + action groups (email / webhook)                                 |
| Entra       | Enterprise app **Owners** / **Privileged Identity Management** (if licensed)—process, not only code |

---

## C19 — Operational runbooks

| Category  | Technology / tool                                                                            |
| --------- | -------------------------------------------------------------------------------------------- |
| Authoring | **Markdown** in repo `docs/runbooks/` (path per your repo creation)                          |
| Optional  | Internal wiki (**SharePoint**, **Notion**, **Confluence**) if non-devs must edit without Git |

---

## Matrix (component → primary technologies)

| ID               | Primary frameworks / runtimes                                                                               | Primary Azure (or Microsoft) services                       |
| ---------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| C01              | Teams client, Adaptive Cards schema                                                                         | (client-side)                                               |
| C02              | Agents Toolkit, Bot Framework Python, uvicorn                                                               | App Service Linux, Bot Service                              |
| C03              | MSAL, httpx or msgraph-sdk                                                                                  | Microsoft Graph                                             |
| C04              | Bot Framework activity types                                                                                | (logic only; uses C03)                                      |
| C05              | Python, Pydantic                                                                                            | —                                                           |
| C06              | SQLAlchemy + **libsql** (Turso interim, remote); **pyodbc** (Azure SQL target); optional **azure-mgmt-sql**; **azure-cosmos** *(scale-up path)* | **Turso Cloud** (interim) / **Azure SQL Database** (target) / Cosmos (if adopted) |
| C07              | httpx, MSAL, Pydantic                                                                                       | D365 F&O OData endpoint                                     |
| C08              | azure-keyvault-secrets, azure-identity                                                                      | Key Vault                                                   |
| C09              | anthropic, openai (Azure OpenAI + **Groq** OpenAI-compatible for testing)                                   | Azure OpenAI resource; Groq cloud API (non-prod or flagged) |
| C10              | Python, YAML/JSON policy                                                                                    | Entra app roles                                             |
| C11 *(optional)* | OpenTelemetry or App Insights SDK                                                                           | Application Insights *(if enabled)*                         |
| C12              | Azure Functions Python v2                                                                                   | Function App (Consumption)                                  |
| C13              | azure-storage-queue                                                                                         | Storage account (queues)                                    |
| C14              | Adaptive Cards JSON                                                                                         | Teams                                                       |
| C15              | GitHub Actions, az CLI, Bicep/Terraform                                                                     | Deployment targets                                          |
| C16              | VS Code, Dev Tunnels, Functions Core Tools                                                                  | —                                                           |
| C17              | Turso PITR (interim) / Azure SQL backup & PITR (target)                                                   | Turso Cloud + SQL + optional Blob for exports             |
| C18              | Git, Azure portal                                                                                           | Cost Management                                             |
| C19              | Markdown                                                                                                    | —                                                           |

---

## Related documents

| Document                             | Role                                                         |
| ------------------------------------ | ------------------------------------------------------------ |
| `docs/LTM_SYSTEM_SPEC.md`            | **Master** system specification (source of truth).           |
| `docs/_archive/CLAUDE_1.md`          | Archived historical baseline.                                |
| `docs/LTA_ARCHITECTURE_PRECODE.md`   | Component responsibilities and interfaces (**C01**–**C19**). |
| `docs/LTA_TECHNICAL_REQUIREMENTS.md` | Behavioral **Must/Should/May** requirements (not stack).     |
| `docs/LTA_SYSTEM_DECISIONS.md`       | Normative methodology and cost posture.                      |

---

## Document control


| Version | Date       | Notes                                                            |
| ------- | ---------- | ---------------------------------------------------------------- |
| 0.1     | 2026-05-03 | Initial per-component technology stack.                          |
| 0.3     | 2026-05-03 | Satellite banner; related-docs → `LTM_SYSTEM_SPEC.md` + archive. |
