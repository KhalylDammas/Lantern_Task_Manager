# Assignment authorization (Unit #1) — design spec

**Status:** Implemented and approved (2026-06-10)  
**Queue:** [LTM_CRITICAL_WORK_QUEUE.md](../LTM_CRITICAL_WORK_QUEUE.md) item #1 — **Done**  
**Spec written:** 2026-05-20 · **Owner approval:** 2026-06-10

## Goal

Enforce **who may assign a task to whom** in code before a draft is stored or a task is persisted. The LLM and Adaptive Cards may propose assignees; the server must deny invalid requester → assignee pairs with a clear message.

## Non-goals (this unit)

- Sapience HRMS API or bearer-token integration  
- Live sync DB between HRMS record index and Entra  
- D365 worker records as authorization identity  
- Fixing org-wide Entra `department` / `manager` completeness  
- `role_band` / `FIN-A` style rules (add later via directory fields if needed)  
- Manager verification authorization (Unit #2; may reuse directory `manager_entra_id`)

## Decision summary

| Topic | Choice |
|-------|--------|
| Identity for rules | **`assignment_directory.json`** keyed by Entra object id (~25 staff) |
| Rules | **`assignment_policy.json`** (same-dept, cross-dept, directed edges) |
| Entra / Graph | Optional UX enrichment only; **not** used for allow/deny |
| D365 / HRMS | Out of scope for profiles |

## Architecture

```text
create_task / confirm_task / manual_create_submit
        │
        ▼
  resolve AssignmentProfile(requester_entra_id)
  resolve AssignmentProfile(assignee_entra_id)
        │  (from assignment_directory.json)
        ▼
  evaluate_assignment_policy(requester, assignee)
        │  (from assignment_policy.json)
        ├── allow → continue (draft / persist)
        └── deny  → raise PolicyDeniedError (user-visible message)
```

## Config artefacts

Loaded via `ltm.config.artefacts` (same pattern as `manager_map.json`). Changes go through Git PR (**C18**).

### `src/config/assignment_directory.json`

Canonical roster for LTM authorization. One entry per internal user who may request or receive tasks.

```json
{
  "version": 1,
  "notes": "Maintained by ops/HR. Entra object id is the primary key.",
  "employees": {
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": {
      "display_name": "Jane Doe",
      "employee_code": "LSS229",
      "department_code": "FIN",
      "manager_entra_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
      "active": true
    }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `display_name` | No | Audit / error messages |
| `employee_code` | No | Lantern code (e.g. LSS229); not used for matching |
| `department_code` | Yes | One of `FIN`, `PROC`, `PROJ`, `HR`, `IT` (`DeptCode`) |
| `manager_entra_id` | No | For Unit #2; may duplicate `manager_map` later |
| `active` | No (default true) | `false` → user cannot act as requester or assignee |

**Missing Entra id:** `ProfileNotFoundError` — *"You are not listed in the LTM assignment directory. Contact your administrator."*

**Future:** optional `role_band`, `can_assign_to_departments` per user (overrides policy edges).

### `src/config/assignment_policy.json`

Rules applied to **directory** profiles only.

```json
{
  "version": 1,
  "defaults": {
    "allow_same_department": true,
    "allow_cross_department": false
  },
  "edges": [
    {
      "from": { "department_code": "PROC" },
      "to": { "department_code": "FIN" },
      "bidirectional": false
    },
    {
      "from": { "department_code": "FIN" },
      "to": { "department_code": "IT" },
      "bidirectional": true
    }
  ],
  "deny_edges": []
}
```

**Evaluation order**

1. If requester or assignee not in directory (or `active: false`) → deny.  
2. Apply `deny_edges` (requester matches `from`, assignee matches `to`).  
3. If `requester.department_code == assignee.department_code` and `defaults.allow_same_department` → allow.  
4. For each `edges` entry: if requester matches `from` and assignee matches `to` → allow; if `bidirectional` and reverse matches → allow.  
5. If `defaults.allow_cross_department` and departments differ → allow (only when no edge matrix needed; prefer explicit `edges` for cross-dept).  
6. Else → deny with message naming departments, e.g. *"Assignment from Finance to IT is not allowed under current policy."*

**Matcher semantics (`from` / `to` objects):** all specified keys must match (AND). Supported keys in v1: `department_code`, `entra_object_id`. Empty object `{}` is invalid for edges.

**Self-assignment:** allowed only if policy allows (same department default covers same-dept self; add explicit deny edge if forbidden).

## Code modules

| Module | Responsibility |
|--------|----------------|
| `ltm/policy/profiles.py` | `AssignmentProfile` dataclass; load from directory |
| `ltm/policy/assignment.py` | Load policy; `can_assign(requester, assignee) -> PolicyResult` |
| `ltm/policy/errors.py` | `PolicyDenied`, `ProfileNotFound` with `user_message` |
| `ltm/config/artefacts.py` | `load_assignment_directory()`, `load_assignment_policy()` |

**Public API**

```python
def assert_can_assign(*, requester_entra_id: str, assignee_entra_id: str) -> None:
    """Raise PolicyDenied or ProfileNotFound on failure."""
```

## Enforcement points

| Location | When |
|----------|------|
| `create_task_handler` | Before `stash_draft` |
| `app.py` `confirm_task` | Before `create_from_draft` |
| `app.py` `manual_create_submit` | Before `create_from_draft` |

Do not rely on `assignee_department_code` from the LLM for authorization; resolve assignee profile from directory by `assignee_entra_id`. Mismatch between tool param dept and directory dept → deny (prevents spoofing).

## Graph / mentions (unchanged for auth)

- Mention resolution and Graph search remain for **UX** (picker, agent context).  
- If Graph `department` disagrees with directory, **directory wins** at enforce time.

## Relationship to `manager_map.json`

- **Unit #1:** directory may include `manager_entra_id` for future use.  
- **Unit #2:** prefer single source — either migrate manager lines into `assignment_directory` or keep `manager_map` and document that directory is assign-only. Recommendation: keep both for now; avoid duplicate edits by generating manager_map from directory in a later cleanup.

## Testing

| Case | Expect |
|------|--------|
| Same dept, default allow | allow |
| Cross dept, default deny, no edge | deny |
| PROC → FIN one-way | allow PROC→FIN; deny FIN→PROC |
| FIN ↔ IT bidirectional edge | both directions allow |
| Requester not in directory | ProfileNotFound |
| Assignee not in directory | ProfileNotFound |
| `active: false` | deny |
| Tool dept FIN, directory IT for assignee | deny |

Fixtures: minimal `assignment_directory.json` and `assignment_policy.json` under `tests/fixtures/policy/`.

## Rollout

1. Seed `assignment_directory.json` with pilot users (Entra ids from Teams `/who` or Azure portal).  
2. Set `assignment_policy.json` to match current business rule (likely same-dept + selected cross-dept edges).  
3. Deploy; update `instructions.txt` (Unit #4) to say server enforces policy — agent should not argue with denials.

## Open items (later)

- Merge `manager_map` into directory  
- Per-user `can_assign_to_departments` override list  
- HRMS CSV import → directory (offline, no API)  
- Guest / external users (Unit #6): `active: false` or separate `user_type` in directory

## Approval

- [x] Product owner: directory-first approach approved (2026-05-20)  
- [ ] Policy JSON contents seeded with real roster (pilot placeholders in `assignment_directory.json`)  
- [x] Implementation complete + tests green  
