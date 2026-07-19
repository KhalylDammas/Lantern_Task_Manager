# LTM critical work queue

Sequential implementation queue for **high-risk** changes (agent behavior, workflows, authorization). Work **one active unit at a time**; do not start the next item until the active unit is done, tested, and reviewed.

**Related docs:** [LTA_GAP_REGISTER.md](LTA_GAP_REGISTER.md) (program gaps) · [LTM_SYSTEM_SPEC.md](LTM_SYSTEM_SPEC.md) (behavior source of truth)

---

## How to use this file

1. Move exactly **one** item from **Backlog** to **Active** when you are ready to implement.
2. Add a design spec link under that item before coding (e.g. `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`).
3. On completion, move the item to **Done** with date and PR/commit reference.
4. Policy and workflow rules must be **enforced in code** (tools, repository, card handlers)—not only in `instructions.txt` or the LLM prompt.

**Dev-only items** (below) still need a spec and hard guards so they never ship to production, but they may run **in parallel** with one production-critical unit if the team agrees (e.g. while a PR is in review).

---

## Active (max 1)

| Unit                          | Owner | Spec                                                                                   | Started    | Notes                                                          |
| ----------------------------- | ----- | --------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------- |
| **#8 Turso database (C06 interim)** | —     | [2026-05-20-turso-database-design.md](specs/2026-05-20-turso-database-design.md) | 2026-06-10 | **Implemented 2026-06-10 — pending owner review.** Remote-only `sqlalchemy-libsql`; Azure SQL ODBC retained; local-file fallback removed; runbook [turso-bootstrap.md](runbooks/turso-bootstrap.md). Remote spike awaits Turso credentials. |

---

## Backlog (ordered)

Priority order is a **proposal**; reorder when you decide what to tackle first.

| #   | Unit                                   | Summary                                                                                                                                                                                                         | Depends on | Key touchpoints                                           |
| --- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------- |
| 2   | **Manager verification authorization** | Only the assignee’s manager (or configured delegate) may confirm/reject closure. Today: `manager_confirm` / `manager_reject` check status only, not actor vs `manager_map.json` / directory `manager_entra_id`. | #1 done    | `TaskRepository`, `app.py` card verbs, `manager_map.json` |
| 3   | **Workflow alignment**                 | Align create/close/verify paths with `state_machine.py` and spec states (e.g. create currently lands in `IN_PROGRESS`; CREATED/ASSIGNED may be skipped).                                                        | —          | `repository.py`, `state_machine.py`, card flows           |
| 4   | **Agent behavior hardening**           | Narrow `instructions.txt` to stable rules; return clear policy errors from tools; reduce reliance on prose blocks for security.                                                                                 | #1–#3      | `instructions.txt`, tool descriptions                     |
| 5   | **JSON message envelope**              | Wrap inbound user content as versioned JSON (requester profile, time/timezone, conversation, mentions) for agent context.                                                                                       | #4         | `app.py`, `ltm/bot/agent_envelope.py`, `instructions.txt` |
| 6   | **Guest / external user policy**       | Document and enforce whether guests can request, be assigned, or verify (per FR-ID-05 gap).                                                                                                                     | #1         | policy module, Entra/Teams identity checks                |

### Dev enablement (non-production; still requires guards + spec)

| #   | Unit                       | Summary                                                                                                                                                                                   | Depends on                 | Key touchpoints                                                       |
| --- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | --------------------------------------------------------------------- |
| 7   | **Dev user impersonation** | Act as another directory user locally to test assignment policy, manager flows, and cards without switching Teams accounts. **Must be impossible in prod** (env + allowlist + audit log). | #1 done (meaningful tests) | `sender_user_ref` / `set_turn_context`, `get_actor()`, local env only |

**Suggested scope for #7 (to spec before code):**

- Override actor Entra id only when `TEAMSFX_ENV=local` (and/or explicit `LTM_DEV_IMPERSONATION_ENABLED=true`).
- Allowlist: real signed-in developer id(s) → permitted impersonation targets from `assignment_directory.json`.
- Trigger: env var and/or dev-only chat command (e.g. `/impersonate Jabir`) stored per `conversation_id`.
- Log every impersonated turn (real user → effective user).
- Show effective user in agent replies/cards during dev (banner or prefix) to avoid confusion.
- **Do not** use for production Teams or shared dev bot without team agreement.

---

## Deferred / needs decision

| Topic                      | Question                                                                                | Blocks  |
| -------------------------- | --------------------------------------------------------------------------------------- | ------- |
| Assignment rule set        | **Resolved:** `assignment_directory.json` + `assignment_policy.json` (directory-first). | —       |
| C06 interim store          | **Resolved:** Turso Cloud, remote-only `libsql`; Azure SQL remains target when cost approved. See [2026-05-20-turso-database-design.md](specs/2026-05-20-turso-database-design.md). | Unit #8 |
| Sapience HRMS              | API blocked. Out of scope; optional CSV → directory later.                              | —       |
| Impersonation UX           | Env-only vs `/impersonate` command vs Playground header                                 | Unit #7 |
| Impersonation allowlist    | Only Khalyl, or any IT admin, or config file                                            | Unit #7 |
| JSON envelope timezone     | Default IANA zone vs per-user preference                                                | Unit #5 |
| Envelope vs mention blocks | Structured `mentions[]` in JSON                                                         | Unit #5 |

---

## Done

| Unit                            | Completed  | PR / commit                                                                                                      | Notes                                                                                                      |
| ------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| **#1 Assignment authorization** | 2026-06-10 | Branch `feature/assignment-authorization` (`287eee9`, `e41f1c2`, `0bb8613`); **approved by owner 2026-06-10** | Directory + policy JSON, CEO direct-report rule, 8 employees seeded, enforcement in `tools.py` + `app.py` |

---

## Context (from discovery)

- **Inbound path:** Teams message → `resolve_mentions_in_text` → `redact` → `ChatPrompt.send` (`instructions.txt` + `ListMemory`).
- **Actor today:** `sender_user_ref(activity)` → `set_turn_context` → `get_actor()` for tools and authorization.
- **Local dev:** `BOT_SKIP_AUTH`, `TEAMSFX_ENV=local` already exist — impersonation should hook the same “non-prod” gate.
- **Do not** track product-wide gaps here—use [LTA_GAP_REGISTER.md](LTA_GAP_REGISTER.md).

---

_Last updated: 2026-06-10 — Unit #1 Done; #8 Turso implemented and Active pending owner review; #7 dev impersonation in backlog._
