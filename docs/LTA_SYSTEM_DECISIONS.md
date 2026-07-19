# LTA System Decisions & Properties

> **Satellite document.** Master program specification: [`LTM_SYSTEM_SPEC.md`](LTM_SYSTEM_SPEC.md) (**LTM** — Lantern Task Manager).

This document records **agreed** methodologies, frameworks, naming principles, and architectural direction for LTM. It complements `docs/LTA_GAP_REGISTER.md` (prioritized work items). The historical baseline `CLAUDE_1.md` lives in [`_archive/CLAUDE_1.md`](_archive/CLAUDE_1.md).

---

## 1. Purpose and scope

- **Product:** Microsoft Teams–hosted agent (**LTM** — Lantern Task Manager) for operational **task lifecycle** (create, assign, track, remind, verify). Work itself stays with humans; ERP remains authoritative for transactions.
- **Users:** Lantern Systems operational staff (~25) across five departments as described in [`LTM_SYSTEM_SPEC.md`](LTM_SYSTEM_SPEC.md).
- **Non-goals for this document:** Detailed field-by-field D365 tables (those remain validated with the D365 administrator and environment metadata).

---

## 2. Canonical identity model

| Decision                   | Detail                                                                                                                                                                            |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Primary user key**       | Microsoft **Entra ID** identity associated with Teams (e.g. `aadObjectId` / tenant-scoped user id as exposed in Bot Framework activities—exact field captured in implementation). |
| **Display and HR context** | Name, department, and similar attributes come from **Microsoft Graph** directory data and/or maintained config where Graph is insufficient.                                       |
| **D365 Workers**           | Used only as **optional enrichment** when a user has a D365 record—not as the mandatory link for assignment or auth. Rationale: not all employees have D365 users.                |
| **Assignment record**      | Persist assignee and requester by **Entra id** plus cached display fields for cards and search.                                                                                   |


**Implication for UX:** Final assignee selection must use **directory-backed controls** or resolved @mentions, not parsed free text alone.

---

## 3. Application framework and delivery

| Decision                    | Detail                                                                                                                                                                                |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Official path**           | **Microsoft 365 Agents Toolkit** for project structure, Teams/Microsoft 365 integration patterns, deployment, and alignment with Microsoft guidance.                                  |
| **Implementation language** | Baseline specifies Python 3.12; retain unless the toolkit default for your scenario prescribes a supported alternative—if so, record an explicit deviation here in a future revision. |
| **Hosting**                 | Azure (existing subscription); specific SKUs are **cost-optimized** per section 7, not copied blindly from the baseline diagram.                                                      |

---

## 4. AI providers and naming conventions

| Topic                    | Convention                                                                                                                                                 |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Primary model**        | Config-driven model id (environment variable or Key Vault reference), e.g. `ANTHROPIC_MODEL_ID`. Do not hardcode version strings in multiple source files. |
| **Fallback model**       | Config-driven Azure OpenAI deployment name + API version; same pattern.                                                                                    |
| **Documentation**        | Refer to models by **config key + vendor documentation link**, not only by snapshot id, so upgrades do not orphan prose.                                   |
| **Tools exposed to LLM** | Stable snake_case or vendor-required names; each tool maps to one backend operation with typed parameters (see D365 access, below).                        |

**Failover philosophy:** Automated model failover may remain, but the **authoritative fallback** is **validated structured input** from the user (forms), not “queue only.”

---

## 5. Privacy and sensitive data handling

| Decision                  | Detail                                                                                                                                                                                                                                                      |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Stakeholder awareness** | Residual privacy risk from LLM processing is acknowledged by leadership; engineering still implements **mitigations**.                                                                                                                                      |
| **Censoring layer**       | Before sending text to an LLM (and optionally before certain logs), replace sensitive segments with **placeholders** (`[REDACTED_VENDOR]`, etc.) while retaining real values in **application-controlled storage** for task execution and D365 correlation. |
| **Consistency**           | Redaction rules should be **centralized** (single module or policy file) so prompts, logs, and support tooling stay aligned.                                                                                                                                |

Exact taxonomy of sensitive fields is maintained with Security / HR input and may reference D365 field classes once validated.

---

## 6. D365 read-only integration (methodology)

| Decision               | Detail                                                                                                                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Access**             | OAuth 2.0 client credentials; **read-only** service principal; no write paths in application code.                                                                                         |
| **Truth for entities** | Entity set names, filters, and columns are **validated with the D365 administrator** against `$metadata` and a target environment.                                                         |
| **Agent interface**    | The LLM (and Teams UI) should call **curated application APIs** (“lookup vendor,” “get PO”) implemented with httpx/OData internally—not open-ended OData URL composition inside the model. |
| **Resilience**         | Retries with backoff on **429** and transient errors; structured errors surfaced to the user.                                                                                              |

Environment-specific base URL and legal entity remain as in the baseline unless the admin specifies otherwise.

---

## 7. Data persistence and cost-conscious Azure footprint

**Principle:** Meet reliability and audit needs for ~25 users **without** defaulting to the most expensive pairing of services.

| Area                   | Direction                                                                                                                                                                                                                                                                                                                                                             |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Task + audit store** | Prefer a **single primary transactional store** for MVP unless compliance mandates separation. **Target architecture:** **Azure SQL Database** (see `docs/LTA_COMPONENT_TECH_STACK.md` **C06**) — preferred when budget is approved. **Interim operational (2026-05-20):** **Turso Cloud**, remote-only via `libsql`, until Azure SQL cost is approved; ODBC/Azure SQL code paths remain for future cutover. See [specs/2026-05-20-turso-database-design.md](specs/2026-05-20-turso-database-design.md). **Cosmos DB for NoSQL** remains a scale-up path. |
| **Reporting**          | Defer dedicated reporting database until reporting requirements exceed what the primary store + export can satisfy.                                                                                                                                                                                                                                                   |
| **API Management**     | Omit from MVP unless required by enterprise policy or multi-client API surface.                                                                                                                                                                                                                                                                                       |
| **Functions**          | Retain timer-based jobs (daily summary, escalation, cache sync) on Consumption or equivalent cost-aware plan.                                                                                                                                                                                                                                                         |
| **Secrets**            | Azure Key Vault + managed identity remains the default pattern.                                                                                                                                                                                                                                                                                                       |
| **Observability**      | Application Insights at sampling appropriate to cost; avoid high-cardinality PII in custom dimensions.                                                                                                                                                                                                                                                                |

**Trigger list for scale-up** (examples): sustained RU throttling, audit retention exceeding store limits, formal BI on a warehouse, or compliance audit requiring WORM / SQL-only tooling.

---

## 8. Microsoft Graph and proactive messaging

Document in deployment runbooks (to be expanded):

- Required **application permissions** and **delegated** permissions (if any) for: directory search / user read, chat creation or continuation, sending proactive 1:1 messages.
- **Admin consent** process and renewal.
- Behavior when **policy blocks** proactive delivery (user blocked bot, tenant restriction).

Exact permission names should be copied from Microsoft Graph documentation at implementation time and reviewed with IT.

---

## 9. Ownership and governance

| Role                       | Responsibility                                                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Developer**              | Implementation, security updates, infrastructure as code, monitoring, incident debugging.                                                        |
| **Owner (CEO / delegate)** | Prioritization, approval of spend and subprocessors, acceptance of residual risk, escalation paths for HR/org changes (manager map, catalogues). |
| **Shared**                 | Change windows, production config updates, and annual permission review.                                                                         |


---

## 10. Configuration artifacts (unchanged intent, clarified ownership)

| Artifact         | Purpose                                  | Owner approval           |
| ---------------- | ---------------------------------------- | ------------------------ |
| Task catalogue   | Task types, SLAs, default D365 ref hints | Department heads / owner |
| Manager map      | Reporting line for verification          | HR / owner               |
| Escalation rules | Timers and thresholds                    | Owner                    |

---

## 11. Relation to other documents

| Document                                   | Role                                                                             |
| ------------------------------------------ | -------------------------------------------------------------------------------- |
| `docs/LTM_SYSTEM_SPEC.md`                  | **Master** system specification (source of truth).                               |
| `docs/_archive/CLAUDE_1.md`                | Archived baseline (historical reference only).                                  |
| `docs/LTA_TECHNICAL_REQUIREMENTS.md`       | Behavioral **Must/Should/May** requirements; traceability to **C01**–**C19**.    |
| `docs/LTA_COMPONENT_TECH_STACK.md`         | Per-component **technology, tools, frameworks, Azure** choices.                  |
| `docs/LTA_ARCHITECTURE_PRECODE.md`         | Pre-code **components and tools**; architecture-level gap recognition.           |
| `docs/LTA_GAP_REGISTER.md`                 | Prioritized gaps and `✅` status (code, architecture, or normative spec).         |
| `docs/LTA_SYSTEM_DECISIONS.md` (this file) | **Normative** agreed direction for implementation and procurement conversations. |

When implementation choices diverge from this file, either **update this file** or add an appendix with rationale and date.

---

## Document control

| Version | Date       | Notes                                                                                                                      |
| ------- | ---------- | -------------------------------------------------------------------------------------------------------------------------- |
| 0.1     | 2026-05-03 | Initial decisions from stakeholder review (identity, toolkit, failover forms, D365 methodology, privacy, cost, ownership). |
| 0.2     | 2026-05-03 | Linked `LTA_ARCHITECTURE_PRECODE.md` in document index (§11).                                                              |
| 0.3     | 2026-05-03 | Linked `LTA_TECHNICAL_REQUIREMENTS.md` in document index (§11).                                                            |
| 0.4     | 2026-05-03 | Linked `LTA_COMPONENT_TECH_STACK.md`; clarified TR doc as behavioral-only.                                                 |
| 0.6     | 2026-05-03 | Intro + §11: master `LTM_SYSTEM_SPEC.md`, LTM naming, archived baseline pointer. |
