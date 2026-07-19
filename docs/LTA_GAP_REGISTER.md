# LTA Gap Register

> **Satellite document.** Master program specification: [`LTM_SYSTEM_SPEC.md`](LTM_SYSTEM_SPEC.md) (**LTM** — Lantern Task Manager).

This document captures **adjustments** relative to the program baseline (see master spec and archived [`_archive/CLAUDE_1.md`](_archive/CLAUDE_1.md)). Items are grouped by **domain**, then by **severity** within each domain.

**Status:** `✅` means the gap is **closed for planning purposes** by any of: **(a)** shipped **code**; **(b)** **system architecture recognition** in `docs/LTA_ARCHITECTURE_PRECODE.md` (a named component and tool assignment); **(c)** normative decisions in `docs/LTA_SYSTEM_DECISIONS.md`; **(d)** explicit agreement in this register. Unmarked items still need policy choice, tenant-specific content, or discretionary product scope.

**Severity guide**
Component IDs (**C01**–**C19**) refer to `docs/LTA_ARCHITECTURE_PRECODE.md` §3.

| Level            | Meaning                                                                               |
| ---------------- | ------------------------------------------------------------------------------------- |
| **High**         | Blocks correctness, trust, security, or core delivery if unaddressed.                 |
| **Medium**       | Material risk to reliability, cost, or maintainability; should be planned explicitly. |
| **Low**          | Improves polish, speed, or clarity; can follow after core stabilization.              |
| **Nice to have** | Optional enhancements with clear benefit but no dependency for go-live.               |

---

## 1. Domain: Identity, Assignment & Teams UX

Resolving *who* is meant when names collide (e.g. “Muhammad in Finance” vs “Muhammad in Procurement”), and binding users to **Microsoft Entra ID / Teams identities** rather than D365 worker keys when D365 coverage is incomplete.

### High

- ✅ **Entra ID / Teams as canonical user identity.** All routing, “my tasks,” proactive messages, and audit “who” fields must use stable Entra identifiers (e.g. object ID / UPN as agreed in the system spec), not D365 `PersonnelNumber`, because not every employee exists in D365. *(See `LTA_SYSTEM_DECISIONS.md` §2.)*
- ✅ **Disambiguation for assignees with similar names.** Natural-language-only resolution is insufficient. The product must support deterministic selection: e.g. **people picker / typeahead**, **Adaptive Card `Input.ChoiceSet` populated from directory search**, or explicit **@mention** resolution via Graph, with **department and job title** shown in the confirmation step. *(See `LTA_SYSTEM_DECISIONS.md` §2, UX implication.)*
- ✅ **“@ mention without channel” clarification.** In Teams 1:1 or group chats, **@mentioning a person does not require the bot to be installed in a team channel.** The gap is not “channel vs chat”; it is **binding the mention to your internal task model**. That requires: (a) reading the mention entity from the incoming activity, (b) storing Entra ID (and display metadata), and (c) never relying on free-text name alone for the final assignee record.

### Medium

- ✅ **Confirmation card must show disambiguation context.** Finance vs Procurement, email, or other agreed fields so the requester can catch wrong-person assignment before commit. *(Covered by confirmation + directory-backed selection in `LTA_SYSTEM_DECISIONS.md` §2.)*
- **Guest users / external IDs.** Policy for whether external guests can be assignees or requesters; if allowed, document how their IDs are stored and verified.

### Low

- ✅ **Fallback when directory search returns no results.** Clear bot message and link to structured form (see AI / Failover domain). *(Aligned with structured manual capture in `LTA_SYSTEM_DECISIONS.md` §4.)*

### Nice to have

- **Preferred name / phonetic matching** in search to reduce spelling friction (still subject to explicit confirm).

---

## 2. Domain: Application Framework & Delivery

Moving from ambiguous “Teams SDK for Python *or* …” to a single **official** path aligned with Microsoft’s current toolkit.

### High

- ✅ **Standardize on Microsoft 365 Agents Toolkit** for scaffolding, configuration, deployment patterns, and alignment with Microsoft’s documented lifecycle for Teams / Microsoft 365 agents. *(See `LTA_SYSTEM_DECISIONS.md` §3.)*

### Medium

- ✅ **Map existing LTA modules** (FastAPI webhook, Functions timers, D365 client) to the toolkit’s recommended layout and hosting options so one repository does not fork into two incompatible deployment stories. *(Decomposed into **C02**–**C19** in `LTA_ARCHITECTURE_PRECODE.md` §3; physical repo layout follows Agents Toolkit scaffold.)*

### Low

- ✅ **CI/CD** templates from the toolkit vs custom GitHub Actions: pick one default and document exceptions. *(Default **C15**: GitHub Actions + toolkit CLI/tasks; see `LTA_ARCHITECTURE_PRECODE.md` §3.)*

### Nice to have

- ✅ **Local dev ergonomics** (emulator, tunneling, sample manifests) fully captured in the system decisions doc for onboarding. *(**C16** in `LTA_ARCHITECTURE_PRECODE.md` §3.)*

---

## 3. Domain: AI, Failover & Input Capture

Replacing “queue and hope” with a **reliable human path** when models are unavailable or untrusted.

### High

- ✅ **Structured manual task capture.** When primary (and optional fallback) LLM paths fail, or when the user opts out of NL, the user can **fill validated fields** (type, description, assignee from directory, due date, priority, optional D365 refs) and submit; the system validates and persists without LLM extraction. *(See `LTA_SYSTEM_DECISIONS.md` §4.)*
- ✅ **Same validation pipeline for NL and manual paths** so behavior is consistent (no duplicate business rules). *(See `LTA_SYSTEM_DECISIONS.md` §4.)*

### Medium

- ✅ **Circuit breaker / timeout behavior** from the baseline remains useful, but the user-visible outcome must be **actionable** (“Continue with form”) not only a generic queued message. *(See `LTA_SYSTEM_DECISIONS.md` §4.)*
- ✅ **Model and configuration naming** must follow vendor-stable, conventional identifiers (environment-driven), documented in `LTA_SYSTEM_DECISIONS.md`. *(See §4 therein.)*

### Low

- ✅ **Telemetry** on NL vs form usage to tune prompts and reduce recurring failures. *(**C11** custom events from **C05**; `LTA_ARCHITECTURE_PRECODE.md` §3, §5.)*

### Nice to have

- ✅ **Optional “draft only” mode** where the LLM proposes fields but never writes until the user submits the form. *(Optional path on **C09** + **C14**; `LTA_ARCHITECTURE_PRECODE.md` §3 **C09**, §5.)*

---

## 4. Domain: D365 Integration & Data Access

Entity names, usability for agents, and coordination with the D365 administrator.

### High

- ✅ **Source of truth from D365 admin.** Validate **entity set names**, **legal entity / company context**, **published data entities**, and **field semantics** against a non-production environment and official metadata—not only documentation tables. *(Process agreed; see `LTA_SYSTEM_DECISIONS.md` §6.)*
- ✅ **Agent-friendly access pattern.** Raw OData with long query strings is hard for LLMs and brittle in code. Plan a **thin internal layer**: typed small queries, curated “lookup” endpoints, or codegen from `$metadata`, so the agent calls **named operations** (“get PO by number”) implemented in your service—not ad-hoc URL assembly in the model. *(See `LTA_SYSTEM_DECISIONS.md` §6.)*

### Medium

- ✅ **Throttling and pagination** policy per entity class; align cache strategy with validated entity behavior. *(**C07** httpx + backoff + `$top`/nextLink; cache timers **C12**; `LTA_ARCHITECTURE_PRECODE.md` §3.)*
- ✅ **Cross-company / `dataAreaId`** rules re-verified after entity list is finalized. *(Per-entity config surface on **C07**; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

### Low

- ✅ **Sandbox vs prod drift** process when new fields or entities are added. *(Separate environments **C15**; promotion discipline with D365 admin; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

### Nice to have

- ✅ **Read replicas or export** for heavy reporting only if reporting outgrows operational stores (see Cost domain). *(Deferred until scale-up; export path from **C06** before replicas; `LTA_ARCHITECTURE_PRECODE.md` §5.)*

---

## 5. Domain: Privacy, Logging & Compliance

Stakeholders accept residual risk today; engineering still implements **defense in depth**.

### High

- ✅ **Censoring / redaction before LLM calls** with **structured placeholders** (e.g. `[VENDOR_ACCOUNT]`, `[CUSTOMER_NAME]`) so prompts and logs minimize raw sensitive strings while the system retains real values in **controlled stores** (task document, encrypted fields) for operational use. *(See `LTA_SYSTEM_DECISIONS.md` §5.)*
- ✅ **Define what counts as sensitive** (PII, financial identifiers, health if any, credentials) and **where** redaction applies (LLM prompt, App Insights, support exports). *(Taxonomy and scopes live in **C10** policy file; enforcement **C10**/**C11**; `LTA_ARCHITECTURE_PRECODE.md` §3, §5—specific field list co-owned with HR/Security.)*

### Medium

- ✅ **Retention windows** for conversation history vs task audit; align with CEO-approved policy. *(**C06** TTL/archival for conversation slices; **C11** telemetry retention; `LTA_ARCHITECTURE_PRECODE.md` §3.)*
- ✅ **Subprocessor / region awareness** for Anthropic and Azure OpenAI endpoints relative to UAE operations. *(Endpoint and Azure region **configuration** on **C08**/**C09**; legal sign-off out of architecture scope; `LTA_ARCHITECTURE_PRECODE.md` §3, §5.)*

### Low

- ✅ **Admin / owner visibility** into redacted vs raw views (who may see unredacted). *(**C10** Entra app roles for privileged readers, TBD with IT; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

### Nice to have

- ✅ **User-facing “privacy summary”** in Teams explaining what the bot sends to AI. *(Optional **C01**/welcome card; `LTA_ARCHITECTURE_PRECODE.md` §5.)*

---

## 6. Domain: Cost, Data Stores & Azure Footprint

Reduce Azure spend versus a default “Cosmos + SQL + APIM + everything” footprint while preserving reliability for ~25 users.

### High

- ✅ **Cost-driven architecture decision record.** Choose a **minimum viable persistence** tier (e.g. single primary store for tasks + audit vs split Cosmos/SQL) with explicit **scale-up triggers** (volume, reporting, compliance) documented in `LTA_SYSTEM_DECISIONS.md`. *(See `LTA_SYSTEM_DECISIONS.md` §7.)*
- ✅ **Eliminate or defer services** that duplicate capability (e.g. API Management if not required by policy) until a trigger is met. *(See `LTA_SYSTEM_DECISIONS.md` §7.)*

### Medium

- ✅ **Azure SQL cost deferral — Turso interim.** Azure SQL remains the **target** C06 store; **Turso Cloud** (remote-only `libsql`) is the **interim operational** store until Azure SQL budget is approved (2026-05-20). See `docs/specs/2026-05-20-turso-database-design.md` and `LTA_SYSTEM_DECISIONS.md` §7.
- ✅ **Backup and restore** for the chosen cheap tier (often overlooked on “lightweight” stores). *(**C17**; `LTA_ARCHITECTURE_PRECODE.md` §3.)*
- ✅ **Function + storage** costs for timers and any queue used for reliability (if retained). *(**C12** Consumption; optional **C13** Queue; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

### Low

- ✅ **Reserved capacity / dev vs prod** separation to avoid prod-grade databases in dev. *(**C15** environment split; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

### Nice to have

- ✅ **Monthly budget alert** and cost review checklist for owner + developer. *(**C18** Azure Cost Management; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

---

## 7. Domain: Operations, Ownership & Documentation

Who runs the system after go-live.

### High

- ✅ **Joint ownership: developer + business owner (CEO delegate).** RACI-style responsibilities for config files (`manager_map`, catalogues), Entra app consent, secrets rotation, and incident response. *(See `LTA_SYSTEM_DECISIONS.md` §9.)*
- ✅ **Graph permissions and proactive messaging** documented end-to-end: required permissions, admin consent, tenant policies, and failure modes when proactive send is blocked. *(Framework in `LTA_SYSTEM_DECISIONS.md` §8; component boundary **C03** in `LTA_ARCHITECTURE_PRECODE.md` §3; tenant-specific permission names and runbook prose still at deployment.)*

### Medium

- ✅ **Runbooks:** manager change, leaver process, wrong-manager verification fix, D365 credential rotation. *(Scope and ownership **C19**; procedural text to be written in `docs/runbooks/`; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

### Low

- ✅ **Version tagging** of config (who changed `manager_map.json`, when). *(**C18** Git history and PR process; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

### Nice to have

- ✅ **Quarterly access review** of bot permissions and service principals. *(**C18** optional cadence with CEO delegate; `LTA_ARCHITECTURE_PRECODE.md` §3.)*

---

## Cross-domain quick index


| Theme                       | Primary domain             | Typical severity |
| --------------------------- | -------------------------- | ---------------- |
| Wrong-person assignment     | Identity & Teams UX        | High             |
| M365 Agents Toolkit         | Application Framework      | High             |
| LLM outage / distrust of NL | AI & Failover              | High             |
| OData / entity truth        | D365 Integration           | High             |
| Wallet-friendly Azure       | Cost & Data Stores         | High             |
| Redaction + placeholders    | Privacy & Compliance       | High             |
| Proactive + Graph consent   | Operations & Documentation | High             |

---

## Document control

| Version | Date       | Notes                                                                               |
| ------- | ---------- | ----------------------------------------------------------------------------------- |
| 0.1     | 2026-05-03 | Initial gap register from feasibility / viability review and stakeholder decisions. |
| 0.4     | 2026-05-03 | Satellite banner; baseline ref → `LTM_SYSTEM_SPEC.md` + `_archive/CLAUDE_1.md`.     |
