# D365 Data Dictionary (LTM)

**Status:** Template for admin sign-off. **Do not treat as authoritative** until validated with the Dynamics 365 administrator against environment `$metadata` and non-production tests.

This document holds **entity set names**, **filter fields**, **pagination rules**, and maps them to LTM façade methods in `src/ltm/d365/facade.py`.

Until each row is marked **Validated**, the façade returns stub JSON and avoids live OData (see `D365Facade._get`).

---

## Document control

| Version | Date       | Changelog                                                 |
| ------- | ---------- | --------------------------------------------------------- |
| 0.1     | 2026-05-03 | Stub created; linked from `LTM_SYSTEM_SPEC.md`.           |
| 0.2     | 2026-05-05 | Named tool ↔ façade mapping and placeholder entity hints. |

---

## Façade method → planned OData surface

| LTM tool / façade method                      | Intended F&O intent               | Placeholder entity set (replace after `$metadata`)    | Key filter fields (example)                |
| --------------------------------------------- | --------------------------------- | ----------------------------------------------------- | ------------------------------------------ |
| `query_d365_po` / `lookup_purchase_order`     | Read PO header by number          | `PurchaseOrderHeaders` *(illustrative)*               | `PurchaseOrderNumber eq '{po}'`            |
| `query_d365_vendor` / `lookup_vendor`         | Resolve vendor by account or name | `Vendors`                                             | `VendorAccountNumber` / `OrganizationName` |
| `query_d365_customer` / `lookup_customer`     | Resolve customer                  | `Customers`                                           | `CustomerAccount` / `OrganizationName`     |
| `query_d365_invoice_ap` / `lookup_invoice_ap` | AP invoice                        | `VendorInvoiceHeaders` *(varies by license)*          | `InvoiceNumber`                            |
| `query_d365_invoice_ar` / `lookup_invoice_ar` | AR invoice                        | `CustInvoiceTable` / `SalesInvoiceHeaders` *(varies)* | `InvoiceId` / `InvoiceAccount`             |
| `query_d365_employee` / `lookup_employee`     | Enrichment-only worker lookup     | `Workers` / `Employees`                               | `$search` or name filters                  |
| `query_d365_project` / `lookup_project`       | Project identifier                | `Projects` / `ProjTable` *(varies)*                   | `ProjectID` / `Name`                       |

**Cross-company:** When legal entities apply, set HTTP header `Company` / `dataAreaId` per environment policy (see `D365Facade._odata_headers`).

---

## Pagination & resilience

- Default page size in façade: **Top N** with explicit `$top` (to be chosen per entity after performance review).
- **`@odata.nextLink`**: extend `_get` with an iterator helper before enabling production traffic.
- **Retries:** `tenacity` on `_get` handles 429/5xx; honour `Retry-After` where present (future hardening).

---

## Configuration keys (environment)

| Variable                                | Purpose                                      |
| --------------------------------------- | -------------------------------------------- |
| `D365_ENVIRONMENT_URL`                  | Base URL to F&O environment (OData root).    |
| `D365_TENANT_ID`                        | Optional; defaults to `TENANT_ID`.           |
| `D365_CLIENT_ID` / `D365_CLIENT_SECRET` | App registration with D365 read scopes.      |
| `D365_DATA_AREA_ID`                     | Optional default company / data area header. |

---

## Historical note

Illustrative entity lists from an older baseline live in [`_archive/CLAUDE_1.md`](_archive/CLAUDE_1.md) (archived) — do not merge into this dictionary without admin validation.
