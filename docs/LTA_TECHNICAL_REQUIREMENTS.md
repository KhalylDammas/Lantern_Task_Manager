# LTA Technical Requirements (Behavioral & Quality)

> **Satellite document.** Master program specification: [`LTM_SYSTEM_SPEC.md`](LTM_SYSTEM_SPEC.md) (**LTM** — Lantern Task Manager).

This document specifies **functional and non-functional requirements** for **LTM**: what the system **must do** and **how it must behave** (Must / Should / May). It consolidates intent from [`LTM_SYSTEM_SPEC.md`](LTM_SYSTEM_SPEC.md) with normative decisions in `docs/LTA_SYSTEM_DECISIONS.md` and component boundaries in `docs/LTA_ARCHITECTURE_PRECODE.md`.

**Per-component technology (languages, SDKs, Azure services, frameworks)** is **not** defined here—see **`docs/LTA_COMPONENT_TECH_STACK.md`**.

**Audience:** developers, architects, security/IT reviewers, and the business owner for acceptance.

**Requirement IDs:** `FR-*` functional, `NFR-*` non-functional, `INT-*` integration, `DM-*` data, `SEC-*` security, `OPS-*` operations. **Must** / **Should** / **May** follow [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) usage below.

**Component traceability:** `C01`–`C19` refer to `docs/LTA_ARCHITECTURE_PRECODE.md` §3.

---

## 1. System context and constraints

| ID     | Statement                                                                                                                                                                                                                    |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CTX-01 | The system is a **Microsoft Teams** conversational agent for **operational task lifecycle** (create, assign, track, remind, verify). Staff perform real work outside the bot; the bot does **not** execute ERP transactions. |
| CTX-02 | Target scale is approximately **25 internal users** across five departments: Finance, Procurement, Projects, HR & Admin, IT & Systems.                                                                                       |
| CTX-03 | **Dynamics 365 Finance & Operations** is integrated **read-only** for reference lookups (PO, vendor, customer, invoices, projects, optional worker enrichment).                                                              |
| CTX-04 | Hosting is **Microsoft Azure** in the organization’s subscription; delivery follows **Microsoft 365 Agents Toolkit** patterns (**C02**, **C16**).                                                                            |
| CTX-05 | **API Management** is **out of scope for MVP** unless enterprise policy mandates it (`LTA_SYSTEM_DECISIONS.md` §7).                                                                                                          |

---

## 2. Identity and directory

| ID       | Priority | Requirement                                                                                                                                                                                                                                                                                                  |
| -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| FR-ID-01 | Must     | The system **Must** treat **Microsoft Entra ID** (Teams/Bot Framework user identity, e.g. object id / tenant-scoped id) as the **canonical** identifier for requesters, assignees, managers in routing, storage, and audit (**C04**, `LTA_SYSTEM_DECISIONS.md` §2).                                          |
| FR-ID-02 | Must     | The system **Must Not** rely on D365 worker / personnel number as the **only** user key for assignment or notifications, because not all employees exist in D365.                                                                                                                                            |
| FR-ID-03 | Must     | Final assignee selection **Must** use **directory-backed** UX (e.g. typeahead, `Input.ChoiceSet` from Graph search, or resolved **@mentions**) plus a **confirmation** step showing disambiguation context (department, email, or other agreed fields)—not free-text name alone (**C03**, **C04**, **C14**). |
| FR-ID-04 | Should   | Optional D365 worker data **May** enrich display when a mapping exists; it **Must Not** override Entra identity for auth or persistence.                                                                                                                                                                     |
| FR-ID-05 | May      | Policy for **guest / external** users as requesters or assignees **Should** be documented when decided; until then implementation **May** default to internal-only (gap: guest policy).                                                                                                                      |

---

## 3. Task lifecycle and workflow

| ID       | Priority | Requirement                                                                                                                                                                                                                                                                                                                                                     |
| -------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-WF-01 | Must     | Tasks **Must** support the state machine: `CREATED` → `ASSIGNED` → `IN_PROGRESS` → `PENDING_CLOSURE` → `PENDING_VERIFICATION` → `VERIFIED` (terminal); **or** from `PENDING_VERIFICATION` → `REOPENED` → `IN_PROGRESS`; **or** `CANCELLED` (terminal, requester-only from applicable states). `OVERDUE` **Must** be a **flag**, not a separate state (**C05**). |
| FR-WF-02 | Must     | Task identifiers **Must** follow `LTM-{DEPT}-{YEAR}-{SEQ}` with department codes **FIN**, **PROC**, **PROJ**, **HR**, **IT** and a four-digit per-department-per-year sequence (**C05**).                                                                                                                                                                       |
| FR-WF-03 | Must     | Priorities **Must** include at least: Critical, High, Medium, Low (baseline alignment).                                                                                                                                                                                                                                                                         |
| FR-WF-04 | Must     | Cross-department assignment **Must** be allowed.                                                                                                                                                                                                                                                                                                                |
| FR-WF-05 | Must     | Task creation **Must** require user **confirmation** (e.g. Adaptive Card) before persisting after NL or form capture (**C01**, **C14**, **C05**).                                                                                                                                                                                                               |
| FR-WF-06 | Must     | Task closure by assignee **Must** collect **completion notes** and move the task to **PENDING_VERIFICATION** pending manager action (**C05**).                                                                                                                                                                                                                  |
| FR-WF-07 | Must     | Manager verification **Must** offer **Confirm** and **Reject (reason required)**; confirm → **VERIFIED**; reject → **REOPENED** with reason to assignee (**C01**, **C05**).                                                                                                                                                                                     |
| FR-WF-08 | Must     | Manager routing **Must** use configurable mapping (e.g. `manager_map`) plus Graph where needed (**C05**, config artifacts).                                                                                                                                                                                                                                     |
| FR-WF-09 | Should   | Escalation for overdue work **Should** follow configurable day thresholds (e.g. notify manager, then department head, then CEO delegate) per `escalation_rules` (**C12**, **C05**).                                                                                                                                                                             |
| FR-WF-10 | Should   | A **daily summary** of pending tasks **Should** be delivered proactively per schedule (baseline: aligned to business morning; UTC timer configurable) (**C12**, **C03**).                                                                                                                                                                                       |

---

## 4. Natural language, AI, and structured fallback

| ID       | Priority | Requirement                                                                                                                                                                                                                                                      |
| -------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-AI-01 | Must     | Primary LLM, fallback LLM, and any **optional test route** (e.g. Groq OpenAI-compatible) **Must** be **configuration-driven** (no hardcoded model version strings scattered in code; Key Vault / app settings) (`LTA_SYSTEM_DECISIONS.md` §4, **C08**, **C09**). |
| FR-AI-02 | Must     | LLM-invoked capabilities **Must** be exposed as **named tools** mapping 1:1 to typed backend operations (no ad-hoc D365 URL building inside the model) (**C09**, **C07**).                                                                                       |
| FR-AI-03 | Must     | All outbound content to the LLM **Must** pass through a **central redaction / placeholder** layer per policy (**C10**).                                                                                                                                          |
| FR-AI-04 | Must     | When LLM paths are unavailable (timeout, circuit open, or user preference), the user **Must** be able to complete **validated structured forms** with the **same validation rules** as NL-derived payloads (**C14**, **C05**).                                   |
| FR-AI-05 | Should   | Circuit breaker / timeout behavior **Should** surface an **actionable** outcome (e.g. “Continue with form”), not a dead-end message only (**C09**, **C02**).                                                                                                     |
| FR-AI-06 | May      | A future **draft-only** NL mode (proposals never persist until form submit) **May** be implemented on **C09**/**C14** per architecture.                                                                                                                          |

---

## 5. D365 integration

| ID          | Priority | Requirement                                                                                                                                                                              |
| ----------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| INT-D365-01 | Must     | D365 access **Must** use **OAuth 2.0 client credentials** (MSAL) with a **read-only** service principal; application code **Must Not** perform OData writes (**C07**).                   |
| INT-D365-02 | Must     | Entity sets, filters, legal entity / company context, and columns **Must** be **validated** with the D365 administrator against environment `$metadata` before production use (**C07**). |
| INT-D365-03 | Must     | The service **Must** implement **retry with exponential backoff** on HTTP **429** and transient failures (**C07**).                                                                      |
| INT-D365-04 | Must     | OData access **Must** use **pagination** (`$top` + nextLink or equivalent) where result sets can exceed single-page limits (**C07**).                                                    |
| INT-D365-05 | Must     | **Cross-company** / `dataAreaId` behavior **Must** be explicit per-entity **configuration**, not implicit in prompts (**C07**).                                                          |
| INT-D365-06 | Should   | Optional **timer-driven cache refresh** for low-churn reference entities **Should** respect TTL policy agreed with the D365 admin (**C12**, **C07**).                                    |

---

## 6. Microsoft Teams and Graph

| ID           | Priority | Requirement                                                                                                                                                                                    |
| ------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| INT-TEAMS-01 | Must     | User interactions **Must** use **Adaptive Cards** (or toolkit-equivalent) for confirmations, assignments, daily summary, verification, and status where applicable (**C01**).                  |
| INT-GRAPH-01 | Must     | Directory search, proactive 1:1 delivery, and other Graph operations **Must** use permissions and consent documented in deployment runbooks (`LTA_SYSTEM_DECISIONS.md` §8, **C03**).           |
| INT-GRAPH-02 | Should   | When proactive delivery fails (user blocked bot, policy), the system **Should** log to host diagnostics and, if **C11** is enabled, alert ops; degrade gracefully without data loss (**C03**). |

---

## 7. Data model and persistence

| ID    | Priority | Requirement                                                                                                                                                                                                                                                                                                                                                      |
| ----- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DM-01 | Must     | The system **Must** persist tasks with at least: stable id, type, department, description, status, priority, `createdBy` / `assignedTo` (**Entra id** + cached display fields), due date, timestamps, closure and verification fields, overdue flag, escalation metadata, structured **D365 references**, and an **append-only audit trail** (**C06**, **C05**). |
| DM-02 | Must     | `createdBy` / `assignedTo` in stored documents **Must** use **Entra-backed** identity fields; legacy examples using only D365 personnel numbers in JSON **Must** be treated as non-normative for identity.                                                                                                                                                       |
| DM-03 | Should   | Short **conversation context** for UX (e.g. last N turns per user) **Should** be bounded; retention **Should** follow CEO-approved policy with optional TTL on **C06** data; telemetry retention applies only when **C11** is enabled (**C06**).                                                                                                                 |
| DM-04 | Must     | Timer jobs **Must** use **idempotency** keys or equivalent so duplicate sends do not duplicate side effects (**C06**, **C12**).                                                                                                                                                                                                                                  |
| DM-05 | Must     | MVP **Must** use a **single primary transactional store** unless compliance forces split. **Target stack:** **Azure SQL Database** with a documented **scale-up path** (e.g. Cosmos DB for NoSQL) per triggers in `LTA_SYSTEM_DECISIONS.md` §7 (**C06**). **Interim operational (2026-05-20):** **Turso Cloud** (remote-only) until Azure SQL budget is approved — see `docs/specs/2026-05-20-turso-database-design.md`. |
| DM-06 | Should   | Backup / replication for the primary store **Should** meet agreed RPO/RTO (e.g. GRS/GZRS and/or export jobs) (**C17**).                                                                                                                                                                                                                                          |

---

## 8. Scheduling and background processing

| ID        | Priority | Requirement                                                                                                                                                                                              |
| --------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-SCH-01 | Must     | Scheduled jobs **Must** run on **Azure Functions** with **timer triggers** (Python 3.12 aligned with app) for at least: daily task summary, overdue escalation scan, optional D365 cache sync (**C12**). |
| FR-SCH-02 | May      | **Azure Queue Storage** **May** be introduced (**C13**) if load testing shows need for decoupling or retry of proactive batches.                                                                         |

---

## 9. Security and secrets

| ID     | Priority | Requirement                                                                                                                                                                          |
| ------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| SEC-01 | Must     | Secrets (API keys, client secrets, model deployment names where sensitive) **Must** reside in **Azure Key Vault**; runtime **Must** use **managed identity** to read them (**C08**). |
| SEC-02 | Must     | Unredacted operational or support views of sensitive fields **Must** be restricted using **Entra application roles** (or equivalent) agreed with IT (**C10**).                       |
| SEC-03 | Should   | Structured logs and telemetry **Should** avoid high-cardinality raw PII; dimensions **Should** favor ids and hashed/redacted labels (**C10**; **C11** when enabled).                 |
| SEC-04 | Must     | All external I/O **Must** use **TLS**; no secrets in source control or CI logs.                                                                                                      |

---

## 10. Observability and quality

| ID          | Priority | Requirement                                                                                                                                                                                      |
| ----------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| NFR-OBS-01  | Must     | The system **Must** emit **structured logs** to the compute host’s default diagnostic pipeline (e.g. App Service / Functions logs viewable without a separate APM resource).                     |
| NFR-OBS-02  | May      | **Application Insights** / OpenTelemetry export (**C11**) **May** be enabled for distributed traces, dashboards, and custom events (e.g. NL vs form); **C11** is **not** an MVP hard dependency. |
| NFR-OBS-03  | May      | When **C11** is enabled, log and metric **retention** and sampling **Should** align with CEO-approved policy and cost targets.                                                                   |
| NFR-QUAL-01 | Should   | Core domain and integration modules **Should** maintain **automated tests** (unit + integration where feasible); target coverage **Should** be agreed (baseline suggested ≥80% on core modules). |
| NFR-QUAL-02 | Must     | The service **Must Not** terminate the process on expected external API failures; errors **Must** be handled, logged, and surfaced to users in a safe form (**C02**, **C05**).                   |

---

## 11. Performance and reliability

| ID          | Priority | Requirement                                                                                                                                                                          |
| ----------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| NFR-PERF-01 | Should   | Typical interactive turns (excluding LLM latency) **Should** complete within a **few seconds** under normal load for ~25 users.                                                      |
| NFR-PERF-02 | Should   | LLM calls **Should** use **timeouts** consistent with circuit-breaker policy (baseline order of magnitude: configurable, e.g. tens of seconds max per policy).                       |
| NFR-REL-01  | Must     | Critical persistence operations **Must** be **durable**; partial writes **Must** be avoided or compensated using **SQL transactions** or equivalent patterns appropriate to **C06**. |

---

## 12. Cost, environments, and delivery

| ID          | Priority | Requirement                                                                                                                                               |
| ----------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NFR-COST-01 | Must     | MVP design **Must** avoid redundant paid services (e.g. no API Management unless required) per `LTA_SYSTEM_DECISIONS.md` §7.                              |
| NFR-COST-02 | Should   | **Azure Cost Management** budgets/alerts **Should** be configured for owner + developer visibility (**C18**).                                             |
| OPS-ENV-01  | Must     | **Dev**, **staging**, and **production** **Must** be separated by configuration and preferably by resource grouping or subscription per policy (**C15**). |
| OPS-ENV-02  | Must     | CI/CD **Must** automate build and deploy using **GitHub Actions** and Agents Toolkit CLI/tasks as the default (**C15**).                                  |

---

## 13. Operations and governance

| ID     | Priority | Requirement                                                                                                                                                                                            |
| ------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| OPS-01 | Must     | **Developer** and **business owner (CEO delegate)** responsibilities for config, consent, secrets rotation, and incidents **Must** be documented and followed (`LTA_SYSTEM_DECISIONS.md` §9, **C18**). |
| OPS-02 | Should   | Operational **runbooks** **Should** exist for manager change, leaver, wrong verification, D365 credential rotation, and incident response (**C19**).                                                   |
| OPS-03 | Should   | Config artifacts affecting behavior (`manager_map`, catalogues, escalation rules) **Should** change via **version-controlled** process (e.g. Git PR) (**C18**).                                        |
| OPS-04 | May      | **Quarterly** access review of app registrations and service principals **May** be scheduled with the owner (**C18**).                                                                                 |

---

## 14. Privacy and compliance (technical)

| ID    | Priority | Requirement                                                                                                                                                                                                           |
| ----- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CP-01 | Must     | A **machine-readable sensitivity policy** **Must** define what classes of data are redacted, placeholder format, and which sinks (LLM, logs, exports) apply (**C10**); taxonomy content is co-owned with HR/Security. |
| CP-02 | Should   | Endpoint and Azure **region** choices for AI and data processing **Should** be documented for subprocessor and residency discussions; configuration **Must** be environment-specific (**C08**, **C09**).              |
| CP-03 | May      | A user-visible **privacy summary** card or link **May** be offered per architecture (**C01**).                                                                                                                        |

---

## 15. Traceability summary (requirements → components)

| Area                  | Primary components        |
| --------------------- | ------------------------- |
| Teams UX, cards       | **C01**, **C14**          |
| Ingest, orchestration | **C02**                   |
| Graph, proactive      | **C03**                   |
| Identity binding      | **C04**                   |
| Domain logic          | **C05**                   |
| Persistence           | **C06**                   |
| D365 reads            | **C07**                   |
| Secrets / config      | **C08**                   |
| LLM                   | **C09**                   |
| Redaction             | **C10**                   |
| Telemetry (optional)  | **C11**                   |
| Timers                | **C12**, optional **C13** |
| CI/CD, dev            | **C15**, **C16**          |
| Backup                | **C17**                   |
| Governance            | **C18**, **C19**          |

---

## 16. Related documents

| Document                           | Role                                                        |
| ---------------------------------- | ----------------------------------------------------------- |
| `docs/LTM_SYSTEM_SPEC.md`          | **Master** system specification; roadmap and examples.      |
| `docs/_archive/CLAUDE_1.md`        | Archived historical baseline.                               |
| `docs/LTA_SYSTEM_DECISIONS.md`     | Normative decisions (identity, toolkit, D365 methodology).  |
| `docs/LTA_ARCHITECTURE_PRECODE.md` | Component and tool decomposition (**C01**–**C19**).         |
| `docs/LTA_GAP_REGISTER.md`         | Gap status and remediation tracking.                        |
| `docs/LTA_COMPONENT_TECH_STACK.md` | Per-component **stack** (SDKs, frameworks, Azure services). |

---

## Document control

| Version | Date       | Notes                                                                                                                                                    |
| ------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0.1     | 2026-05-03 | Initial behavioral and quality requirements.                                                                                                             |
| 0.2     | 2026-05-03 | Renamed scope to behavioral/quality; stack moved to `LTA_COMPONENT_TECH_STACK.md`.                                                                       |
| 0.3     | 2026-05-03 | DM-05/NFR-OBS aligned to Azure SQL MVP and optional **C11**; FR-AI-01 includes configurable test routes (e.g. Groq); satellite banner; master spec refs. |
| 0.4     | 2026-05-03 | Task id prefix **LTM-** (**FR-WF-02**); related-docs table points to `LTM_SYSTEM_SPEC.md`.                                                               |
