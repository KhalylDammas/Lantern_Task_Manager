---
> **Archived (2026-05-03).** Superseded by the program specification: [LTM System Specification](../LTM_SYSTEM_SPEC.md). Retained for history only.
---

# Lantern Task Agent (LTA)

## Project Overview

An AI-powered task lifecycle management bot for Microsoft Teams that manages operational tasks across 5 departments at Lantern Systems Company. The bot creates, assigns, tracks, follows up on, and verifies completion of operational tasks. It does NOT perform tasks — staff do the actual work offline.

- **Users:** 25 staff across Finance, Procurement, Projects, HR & Admin, IT & Systems
- **D365 F&O:** Cloud (LCS-managed), UAE region, base URL: `https://lss-prod.operations.uae.dynamics.com`
- **Legal Entity (dataAreaId):** `lsss`
- **Hosting:** Azure (existing subscription)
- **AI:** Anthropic Claude Haiku 4.5 (primary), Azure OpenAI GPT-4o (fallback)

## Core Principles

1. The bot manages tasks, not transactions. It tracks whether work was done, not the work itself.
2. D365 is read-only. No write operations. Pull reference data only.
3. Humans verify everything. Assignee says "done" → manager confirms via Adaptive Card.
4. Natural language in, structured data out. Users describe tasks in English; bot extracts structure via Claude.
5. Daily accountability: 10 AM popup of pending tasks. Overdue = auto-escalation after 1 day.

---

## Tech Stack

- **Language:** Python 3.12
- **Framework:** FastAPI (async)
- **Bot SDK:** Teams SDK for Python (or M365 Agents SDK)
- **Primary AI:** anthropic SDK → claude-haiku-4-5-20251001
- **Fallback AI:** openai SDK → Azure OpenAI GPT-4o
- **D365:** httpx (async) + MSAL, OAuth2 client credentials, OData REST, read-only
- **Task Store:** Azure Cosmos DB (serverless)
- **Reporting:** Azure SQL Database (Basic 5 DTU)
- **Scheduler:** Azure Functions (Timer triggers)
- **Secrets:** Azure Key Vault (managed identity)
- **Monitoring:** Application Insights

---

## Repository Structure

```
lantern-task-agent/
├── CLAUDE.md
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI entry + /api/messages webhook
│   ├── config.py                # Settings from env / Key Vault
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── handler.py           # Teams activity handler
│   │   ├── cards.py             # Adaptive Card JSON builders
│   │   └── proactive.py         # Proactive messaging via Graph API
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── claude_client.py     # Anthropic API with tool use
│   │   ├── openai_client.py     # Azure OpenAI fallback
│   │   ├── failover.py          # Circuit breaker + cascade
│   │   ├── tools.py             # Tool definitions for Claude
│   │   └── prompts.py           # System prompt templates
│   ├── d365/
│   │   ├── __init__.py
│   │   ├── client.py            # Async OData client (read-only)
│   │   ├── auth.py              # MSAL token + cache
│   │   ├── entities.py          # Pydantic models for D365 entities
│   │   └── cache.py             # Cosmos-based cache with TTL
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── models.py            # Task Pydantic models + state enum
│   │   ├── service.py           # Task CRUD
│   │   ├── lifecycle.py         # State machine transitions
│   │   └── catalogue.py         # Task catalogue loader
│   ├── workflow/
│   │   ├── __init__.py
│   │   ├── verification.py      # Manager verification routing
│   │   ├── escalation.py        # Overdue detection + escalation
│   │   └── manager_map.py       # User → manager lookup
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── cosmos.py            # Cosmos DB repository
│   │   └── sql.py               # Azure SQL audit writer
│   └── notifications/
│       ├── __init__.py
│       ├── graph.py             # Microsoft Graph API client
│       └── daily_popup.py       # Daily task summary card builder
├── functions/
│   ├── daily_popup/             # Timer: 07:00 UTC (10 AM AST)
│   ├── overdue_escalation/      # Timer: 07:15 UTC (10:15 AM AST)
│   └── d365_cache_sync/         # Timer: hourly
├── config/
│   ├── task_catalogue.json
│   ├── manager_map.json
│   └── escalation_rules.json
├── infra/
│   ├── main.bicep
│   ├── parameters.json
│   └── deploy.sh
├── tests/
│   ├── conftest.py
│   ├── test_ai/
│   ├── test_d365/
│   ├── test_tasks/
│   ├── test_workflow/
│   └── test_bot/
└── .github/workflows/deploy.yml
```

---

## D365 F&O Integration (READ-ONLY)

### Authentication

- OAuth 2.0 client credentials via Microsoft Entra ID (MSAL)
- Service principal: read-only role on entities below
- Credentials in Azure Key Vault: d365-client-id, d365-client-secret, d365-tenant-id
- Token endpoint: `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token`
- Resource/scope: `https://lss-prod.operations.uae.dynamics.com/.default`
- All queries must include `?cross-company=true` or `$filter=dataAreaId eq 'lsss'` where applicable

### Entity: PurchaseOrderHeadersV2

**Endpoint:** `/data/PurchaseOrderHeadersV2`


| Field                      | Type     | Example                    | Bot Usage            |
| -------------------------- | -------- | -------------------------- | -------------------- |
| PurchaseOrderNumber        | string   | "PO-2300000001"            | Primary lookup key   |
| OrderVendorAccountNumber   | string   | "V00579"                   | Link to vendor       |
| PurchaseOrderName          | string   | "Takamul Alafkar Printing" | Display name         |
| CurrencyCode               | string   | "SAR"                      | Display in task card |
| PurchaseOrderStatus        | string   | "Invoiced", "Open"         | Show status          |
| ProjectId                  | string   | "" (can be empty)          | Link to project      |
| RequestedDeliveryDate      | datetime | "2023-03-23T12:00:00Z"     | Show in task         |
| PaymentTermsName           | string   | "Net 30D"                  | Reference info       |
| DefaultReceivingSiteId     | string   | "Khobar"                   | Location context     |
| DocumentApprovalStatus     | string   | "Finalized"                | PO state             |
| Email                      | string   | vendor email               | Contact info         |
| AccountingDate             | datetime |                            | Financial date       |
| InvoiceVendorAccountNumber | string   | "V00579"                   | Invoice vendor       |


### Entity: VendorsV3

**Endpoint:** `/data/VendorsV3`


| Field                   | Type   | Example                             | Bot Usage              |
| ----------------------- | ------ | ----------------------------------- | ---------------------- |
| VendorAccountNumber     | string | "V00001"                            | Primary key            |
| VendorOrganizationName  | string | "ALJAMMAZ technologies Company Ltd" | Display name           |
| VendorGroupId           | string | "Local"                             | Category               |
| CurrencyCode            | string | "SAR"                               | Reference              |
| AddressCity             | string | "Riyadh"                            | Location               |
| AddressCountryRegionId  | string | "SAU"                               | Country                |
| PrimaryPhoneNumber      | string | "+ 966 505880935"                   | Contact                |
| OnHoldStatus            | string | "No"                                | Vendor status          |
| DefaultPaymentTermsName | string | "Net 60D"                           | Payment terms          |
| TaxExemptNumber         | string | VAT reg number                      | Tax ref                |
| ZakatRegistrationNumber | string |                                     | Tax ref                |
| VendorSearchName        | string | "Al Jammaz Distributi"              | Short alias for search |
| FormattedPrimaryAddress | string | Full address                        | Display                |


### Entity: CustomersV3

**Endpoint:** `/data/CustomersV3`


| Field               | Type    | Example                         | Bot Usage     |
| ------------------- | ------- | ------------------------------- | ------------- |
| CustomerAccount     | string  | "C0019"                         | Primary key   |
| OrganizationName    | string  | "L&T Hydrocarbon Saudi Company" | Display name  |
| CustomerGroupId     | string  | "40"                            | Category      |
| SalesCurrencyCode   | string  | "USD"                           | Reference     |
| AddressCity         | string  | "Al Khobar"                     | Location      |
| PrimaryContactPhone | string  | "+966 13 519 2967"              | Contact       |
| CreditLimit         | decimal | 0                               | Reference     |
| PaymentTerms        | string  | "Net 30D"                       | Payment terms |
| NameAlias           | string  | "L&T Hydrocarbon Saud"          | Short alias   |
| FullPrimaryAddress  | string  | Full formatted address          | Display       |
| InvoiceAccount      | string  | "C0019"                         | Invoice ref   |


### Entity: VendorInvoiceHeaders

**Endpoint:** `/data/VendorInvoiceHeaders`


| Field                     | Type     | Example                       | Bot Usage      |
| ------------------------- | -------- | ----------------------------- | -------------- |
| InvoiceNumber             | string   | "HSD_SI_00296838"             | Primary key    |
| VendorAccount             | string   | "V00761"                      | Link to vendor |
| VendorName                | string   | "Reza Investment Company Ltd" | Display name   |
| PurchaseOrderNumber       | string   | "PO-2300001005"               | Link to PO     |
| Currency                  | string   | "SAR"                         | Reference      |
| InvoiceDate               | datetime | "2025-04-21"                  | Key date       |
| DueDate                   | datetime | "2025-05-21"                  | Payment due    |
| InvoiceDescription        | string   | "Office Supplies"             | Display        |
| InvoiceReceivedDate       | datetime |                               | Tracking       |
| IsApproved                | string   | "Yes"                         | Status         |
| VendorInvoiceReviewStatus | string   | "InReview"                    | Status         |
| IsOnHold                  | string   | "No"                          | Status         |
| HeaderReference           | string   | "LSSS-018471"                 | Internal ref   |
| BankAccount               | string   | "BSF"                         | Payment info   |


### Entity: Workers

**Endpoint:** `/data/Workers`
**Note:** Cross-company entity (no dataAreaId filter needed)


| Field                  | Type   | Example                    | Bot Usage          |
| ---------------------- | ------ | -------------------------- | ------------------ |
| PersonnelNumber        | string | "582473003"                | Primary key        |
| Name                   | string | "MOHAMMED AMER KHAN"       | Display name       |
| FirstName              | string | "MOHAMMED AMER KHAN"       | First name         |
| NameAlias              | string | "MOHAMMED AMER KHAN"       | Short name         |
| TitleId                | string | "Project Support Engineer" | Job title          |
| WorkerStatus           | string | "Active" / "Terminated"    | Filter active only |
| WorkerType             | string | "Employee"                 | Filter             |
| AddressCountryRegionId | string | "India"                    | Nationality        |


**Filter for active employees:** `$filter=WorkerStatus eq 'Active'`

### Entity: SalesInvoiceHeaders

**Endpoint:** `/data/SalesInvoiceHeaders`


| Field                         | Type     | Example   | Bot Usage        |
| ----------------------------- | -------- | --------- | ---------------- |
| InvoiceNumber                 | string   | "2200002" | Primary key      |
| InvoiceCustomerAccountNumber  | string   | "C0002"   | Link to customer |
| CurrencyCode                  | string   | "USD"     | Reference        |
| TotalInvoiceAmount            | decimal  | 1014.6    | Amount           |
| TotalTaxAmount                | decimal  | 0         | Tax              |
| InvoiceDate                   | datetime |           | Key date         |
| SalesOrderNumber              | string   |           | Linked SO        |
| InvoiceAddressCountryRegionId | string   | "KSA"     | Location         |


### Entity: Projects

**Endpoint:** `/data/Projects`


| Field                            | Type     | Example                                            | Bot Usage        |
| -------------------------------- | -------- | -------------------------------------------------- | ---------------- |
| ProjectID                        | string   | "PRJ000001"                                        | Primary key      |
| ProjectName                      | string   | "Doosan - HCIS Security System in the Yanbu 4 IWP" | Display name     |
| CustomerAccount                  | string   | "C0016"                                            | Link to customer |
| Status                           | string   | "Active"                                           | Filter active    |
| ProjectType                      | string   | "FixedPrice"                                       | Category         |
| ProjectGroup                     | string   | "HCIS"                                             | Group            |
| ProjectContractID                | string   | "Yanbu4-E-002"                                     | Contract ref     |
| WorkerResponsiblePersonnelNumber | string   | "LSS008"                                           | Project manager  |
| StartDate1                       | datetime | "2022-07-28"                                       | Project start    |
| EndDate1                         | datetime | "2023-11-01"                                       | Project end      |
| ProjectStage                     | string   | "User1"                                            | Stage            |
| DurationInDays                   | int      | 462                                                | Duration         |
| JobIdentification                | string   | "LSSS-000401"                                      | Internal job #   |
| Email                            | string   |                                                    | Contact          |


**Filter for active projects:** `$filter=Status eq 'Active'`

### Caching Strategy


| Entity                 | Cache     | TTL    | Reason                  |
| ---------------------- | --------- | ------ | ----------------------- |
| VendorsV3              | Cosmos DB | 5 min  | Rarely changes          |
| CustomersV3            | Cosmos DB | 5 min  | Rarely changes          |
| Workers                | Cosmos DB | 15 min | HR changes infrequent   |
| Projects               | Cosmos DB | 5 min  | Rarely changes          |
| PurchaseOrderHeadersV2 | No cache  | -      | User expects fresh data |
| VendorInvoiceHeaders   | No cache  | -      | User expects fresh data |
| SalesInvoiceHeaders    | No cache  | -      | User expects fresh data |


### Sample OData Queries

```
# PO by number
GET /data/PurchaseOrderHeadersV2?$filter=PurchaseOrderNumber eq 'PO-2300001005'&cross-company=true

# Vendor by name (partial)
GET /data/VendorsV3?$filter=contains(VendorOrganizationName,'ACWA')&$top=5&cross-company=true

# Vendor by account
GET /data/VendorsV3?$filter=VendorAccountNumber eq 'V00001'&cross-company=true

# Customer by name
GET /data/CustomersV3?$filter=contains(OrganizationName,'L%26T')&$top=5&cross-company=true

# AP invoice by number
GET /data/VendorInvoiceHeaders?$filter=InvoiceNumber eq 'HSD_SI_00296838'&cross-company=true

# AR invoice by customer
GET /data/SalesInvoiceHeaders?$filter=InvoiceCustomerAccountNumber eq 'C0002'&cross-company=true

# Active employees
GET /data/Workers?$filter=WorkerStatus eq 'Active'&$top=200

# Active projects
GET /data/Projects?$filter=Status eq 'Active'&cross-company=true

# Project by ID
GET /data/Projects?$filter=ProjectID eq 'PRJ000001'&cross-company=true
```

---

## Task Data Model

### States

```
CREATED → ASSIGNED → IN_PROGRESS → PENDING_CLOSURE → PENDING_VERIFICATION → VERIFIED (terminal)
                                                                           → REOPENED → IN_PROGRESS
                   → CANCELLED (terminal, by requester only)
OVERDUE is a flag on the task, not a separate state.
```

### Task ID Format

`LTA-{DEPT}-{YEAR}-{SEQ}` — e.g., LTA-FIN-2026-0001

- DEPT codes: FIN, PROC, PROJ, HR, IT
- SEQ: 4-digit zero-padded, per department per year

### Cosmos DB Schema

```json
{
  "id": "LTA-FIN-2026-0001",
  "taskType": "LC Opening",
  "department": "Finance",
  "description": "Open LC for PO-2300001005, Reza Investment Company",
  "status": "IN_PROGRESS",
  "priority": "High",
  "createdBy": {"personnelNumber": "593246008", "name": "User Name", "department": "Procurement"},
  "assignedTo": {"personnelNumber": "123456789", "name": "Ahmed Ali", "department": "Finance"},
  "dueDate": "2026-03-15",
  "createdAt": "2026-03-10T08:30:00Z",
  "updatedAt": "2026-03-12T14:22:00Z",
  "closedAt": null,
  "verifiedAt": null,
  "closureNotes": "",
  "rejectionReason": "",
  "isOverdue": false,
  "escalationCount": 0,
  "lastEscalatedAt": null,
  "d365References": {
    "purchaseOrderNumber": "PO-2300001005",
    "vendorAccount": "V00761",
    "vendorName": "Reza Investment Company Ltd",
    "invoiceNumber": null,
    "customerAccount": null,
    "projectId": null
  },
  "auditTrail": [
    {"event": "CREATED", "by": "593246008", "at": "2026-03-10T08:30:00Z", "details": ""},
    {"event": "ASSIGNED", "by": "SYSTEM", "at": "2026-03-10T08:30:05Z", "details": "Notified Ahmed Ali"}
  ],
  "partitionKey": "Finance"
}
```

### Cosmos DB Containers

- **tasks**: partition key `/department`, stores all task documents
- **conversations**: partition key `/userId`, stores last 10 turns per user for Claude context

---

## Claude AI Configuration

### System Prompt (in app/ai/prompts.py)

```
You are the Lantern Task Agent (LTA), an AI assistant managing operational tasks for Lantern Systems Company inside Microsoft Teams.

YOUR ROLE: You CREATE, TRACK, and manage the LIFECYCLE of tasks. You do NOT perform any work. Staff do actual work offline (prepare documents, get signatures, submit to banks, etc.).

RULES:
1. Always confirm task details with user before creating.
2. Never fabricate data. Call D365 tools for real data.
3. Never claim you can perform operational activities.
4. When user mentions PO/vendor/invoice/customer/project — look it up in D365 first.
5. Present D365 data as read-only reference in task cards.
6. Keep responses concise and action-oriented.
7. For task closure, always ask for completion notes.
8. Requester sets assignee, due date, priority. Do not override.
9. Cross-department assignment is allowed.

TASK STATES: CREATED → ASSIGNED → IN_PROGRESS → PENDING_CLOSURE → PENDING_VERIFICATION → VERIFIED or REOPENED
DEPARTMENTS: Finance, Procurement, Projects, HR & Admin, IT & Systems
PRIORITY: Critical, High, Medium, Low
```

### Tool Definitions (in app/ai/tools.py)

Define these tools for Claude's tool_use:

1. **create_task** — Create new task. Required: task_type, description, assignee_name, assignee_department, due_date, priority. Optional: d365_po_number, d365_vendor_account, d365_customer_account, d365_invoice_number, d365_project_id.
2. **list_tasks** — List tasks by filter: my_tasks, my_requests, department, all_overdue, pending_verification. Optional: department, status, limit.
3. **close_task** — Close task by ID with completion_notes. Routes to manager verification.
4. **get_task_status** — Get task by ID or search by keyword.
5. **query_d365_po** — Lookup PO by number. Returns vendor, status, amount, dates.
6. **query_d365_vendor** — Lookup vendor by account or search by name.
7. **query_d365_customer** — Lookup customer by account or search by name.
8. **query_d365_invoice_ap** — Lookup AP invoice by number.
9. **query_d365_invoice_ar** — Lookup AR invoice by number or customer.
10. **query_d365_employee** — Lookup employee by personnel number or name.
11. **query_d365_project** — Lookup project by ID or search by name.

### Failover Logic (in app/ai/failover.py)

```
Primary: claude-haiku-4-5-20251001
Fallback: Azure OpenAI GPT-4o (same system prompt + tools)
Circuit breaker: OPEN after 3 consecutive Claude failures or timeouts (>10s)
Reset: 60 seconds, health-check ping before restoring primary
If both fail: queue for manual, notify user "I'm temporarily unable to process. Your request has been queued."
```

---

## Workflow Specifications

### Task Creation Flow

1. User describes task in natural language
2. Claude extracts: task_type, assignee, department, due_date, priority, D365 references
3. If D365 refs present: bot queries OData to validate and enrich
4. Bot presents confirmation Adaptive Card → user Confirms or Edits
5. Task created in Cosmos DB (state: CREATED → ASSIGNED)
6. Assignee notified via Teams Adaptive Card

### Daily Popup (10 AM AST)

- Azure Function at 07:00 UTC
- Query Cosmos: status IN (ASSIGNED, IN_PROGRESS), grouped by assignee
- Build card: overdue (red) → Critical → High → Medium → Low → by due date
- Send proactive 1:1 message to each user

### Task Closure + Manager Verification

1. Assignee: "Close task LTA-FIN-2026-0001"
2. Bot asks for completion notes
3. State → PENDING_VERIFICATION
4. Manager gets Adaptive Card: [Confirm] [Reject (reason required)]
5. Confirm → VERIFIED, requester notified
6. Reject → REOPENED, assignee notified with reason, state → IN_PROGRESS

### Overdue Escalation

- Azure Function at 07:15 UTC
- Query: IN_PROGRESS AND dueDate < today AND escalatedToday = false
- Day +1: notify manager
- Day +3: notify department head
- Day +7: notify CEO

---

## Config Files

### task_catalogue.json

Department codes: Finance=FIN, Procurement=PROC, Projects=PROJ, HR & Admin=HR, IT & Systems=IT.
Each entry: name, defaultSLA (days), defaultPriority, d365Ref (PO/Vendor/Customer/Invoice/Project/Employee/None).
Start with 10-15 per department. Will be populated from department head spreadsheet.

### manager_map.json

Maps 25 users: personnelNumber → name, department, role, managerPersonnelNumber, managerName, departmentHead.
Must be populated before Phase 4.

### escalation_rules.json

```json
{
  "overdue_thresholds": [
    {"days": 1, "action": "notify_manager"},
    {"days": 3, "action": "notify_department_head"},
    {"days": 7, "action": "notify_ceo"}
  ],
  "daily_popup_time_utc": "07:00",
  "escalation_time_utc": "07:15"
}
```

---

## Adaptive Card Templates (in app/bot/cards.py)

Build these as Python functions returning Adaptive Card JSON:

1. **task_creation_confirm_card** — Task details + D365 data. Buttons: Confirm, Edit, Cancel.
2. **task_assignment_card** — Notify assignee. Buttons: Acknowledge, View Details.
3. **daily_popup_card** — List of pending tasks with priority badges, due dates, overdue flags.
4. **manager_verification_card** — Task details + completion notes. Buttons: Confirm, Reject.
5. **overdue_escalation_card** — Overdue task details. Buttons: Send Reminder, View Task.
6. **task_status_card** — Single task details with full timeline.

---

## Azure Infrastructure (Bicep)

Provision: App Service (B2, Linux, Python 3.12), Azure Bot Service (Standard/Teams), Cosmos DB (serverless, database: lantern-tasks), Azure SQL (Basic 5 DTU), API Management (Consumption), Function App (Consumption, Python 3.12), Key Vault (Standard), Application Insights.

Naming: `lta-{resource}-prod` e.g., lta-app-prod, lta-cosmos-prod.

---

## Coding Conventions

- Async everywhere: all I/O operations must be async (httpx, Cosmos SDK, etc.)
- Pydantic v2 models for all data structures
- Type hints on all functions
- Docstrings on all public functions
- Error handling: never crash on external API failures; log and return graceful error
- Logging: structured JSON logs via Python logging + Application Insights
- Tests: pytest with async support (pytest-asyncio), minimum 80% coverage on core modules
- No secrets in code: all from Key Vault via managed identity or env vars
- All D365 queries include error handling for 429 (throttle) with exponential backoff

