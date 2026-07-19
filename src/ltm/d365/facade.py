"""D365 OData façade (INT-D365-*, C07)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable
from urllib.parse import quote

import httpx
import msal

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from ltm.config.settings import Settings

logger = logging.getLogger(__name__)

_RE_VENDOR_ACCOUNT = re.compile(r"^V\d+$", re.IGNORECASE)
_RE_CUSTOMER_ACCOUNT = re.compile(r"^C\d+$", re.IGNORECASE)
_RE_PROJECT_ID = re.compile(r"^PRJ\d+$", re.IGNORECASE)
_RE_PERSONNEL = re.compile(r"^(ALS{1,2}|LSS)\d{3}$", re.IGNORECASE)

_PO_SELECT = (
    "PurchaseOrderNumber,OrderVendorAccountNumber,PurchaseOrderName,CurrencyCode,"
    "PurchaseOrderStatus,ProjectId,RequestedDeliveryDate,PaymentTermsName,"
    "DefaultReceivingSiteId,DocumentApprovalStatus"
)
_VENDOR_SELECT = (
    "VendorAccountNumber,VendorOrganizationName,VendorGroupId,CurrencyCode,"
    "AddressCity,OnHoldStatus,DefaultPaymentTermsName,VendorSearchName"
)
_CUSTOMER_SELECT = (
    "CustomerAccount,OrganizationName,CustomerGroupId,SalesCurrencyCode,"
    "AddressCity,PaymentTerms,NameAlias"
)
_AP_INVOICE_SELECT = (
    "InvoiceNumber,VendorAccount,VendorName,PurchaseOrderNumber,Currency,"
    "InvoiceDate,DueDate,InvoiceDescription,IsApproved,VendorInvoiceReviewStatus,"
    "IsOnHold,HeaderReference"
)
_AR_INVOICE_SELECT = (
    "InvoiceNumber,InvoiceCustomerAccountNumber,CurrencyCode,TotalInvoiceAmount,"
    "TotalTaxAmount,InvoiceDate,SalesOrderNumber"
)
_WORKER_SELECT = "PersonnelNumber,Name,TitleId,WorkerType,AddressCountryRegionId"
_PROJECT_SELECT = (
    "ProjectID,ProjectName,CustomerAccount,Status,ProjectType,ProjectGroup,"
    "ProjectContractID,WorkerResponsiblePersonnelNumber,StartDate1,EndDate1,JobIdentification"
)


def _escape_odata(value: str) -> str:
    return value.replace("'", "''")


def _build_data_path(entity: str, filter_expr: str, select_fields: str, top: int) -> str:
    query = (
        f"$filter={quote(filter_expr, safe='')}"
        f"&$select={quote(select_fields, safe=',')}"
        f"&$top={top}"
        f"&cross-company=true"
    )
    return f"data/{entity}?{query}"


def _json_response(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _not_found(query: str, entity_label: str) -> dict[str, Any]:
    return {"found": False, "query": query, "message": f"No matching {entity_label}"}


def _map_po(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "purchase_order_number": row.get("PurchaseOrderNumber"),
        "vendor_account": row.get("OrderVendorAccountNumber"),
        "name": row.get("PurchaseOrderName"),
        "status": row.get("PurchaseOrderStatus"),
        "currency": row.get("CurrencyCode"),
        "project_id": row.get("ProjectId") or "",
        "requested_delivery_date": row.get("RequestedDeliveryDate"),
        "payment_terms": row.get("PaymentTermsName"),
        "receiving_site": row.get("DefaultReceivingSiteId"),
        "approval_status": row.get("DocumentApprovalStatus"),
    }


def _map_vendor(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_account": row.get("VendorAccountNumber"),
        "name": row.get("VendorOrganizationName"),
        "group": row.get("VendorGroupId"),
        "currency": row.get("CurrencyCode"),
        "city": row.get("AddressCity"),
        "on_hold": row.get("OnHoldStatus"),
        "payment_terms": row.get("DefaultPaymentTermsName"),
        "search_name": row.get("VendorSearchName"),
    }


def _map_customer(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "customer_account": row.get("CustomerAccount"),
        "name": row.get("OrganizationName"),
        "group": row.get("CustomerGroupId"),
        "currency": row.get("SalesCurrencyCode"),
        "city": row.get("AddressCity"),
        "payment_terms": row.get("PaymentTerms"),
        "name_alias": row.get("NameAlias"),
    }


def _map_ap_invoice(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "invoice_number": row.get("InvoiceNumber"),
        "vendor_account": row.get("VendorAccount"),
        "vendor_name": row.get("VendorName"),
        "purchase_order_number": row.get("PurchaseOrderNumber"),
        "currency": row.get("Currency"),
        "invoice_date": row.get("InvoiceDate"),
        "due_date": row.get("DueDate"),
        "description": row.get("InvoiceDescription"),
        "is_approved": row.get("IsApproved"),
        "review_status": row.get("VendorInvoiceReviewStatus"),
        "is_on_hold": row.get("IsOnHold"),
        "header_reference": row.get("HeaderReference"),
    }


def _map_ar_invoice(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "invoice_number": row.get("InvoiceNumber"),
        "customer_account": row.get("InvoiceCustomerAccountNumber"),
        "currency": row.get("CurrencyCode"),
        "total_amount": row.get("TotalInvoiceAmount"),
        "tax_amount": row.get("TotalTaxAmount"),
        "invoice_date": row.get("InvoiceDate"),
        "sales_order_number": row.get("SalesOrderNumber") or "",
    }


def _map_worker(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "personnel_number": row.get("PersonnelNumber"),
        "name": row.get("Name"),
        "title": row.get("TitleId"),
        "worker_type": row.get("WorkerType"),
        "country_region": row.get("AddressCountryRegionId"),
    }


def _map_project(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": row.get("ProjectID"),
        "name": row.get("ProjectName"),
        "customer_account": row.get("CustomerAccount"),
        "status": row.get("Status"),
        "project_type": row.get("ProjectType"),
        "project_group": row.get("ProjectGroup"),
        "contract_id": row.get("ProjectContractID"),
        "responsible_personnel_number": row.get("WorkerResponsiblePersonnelNumber"),
        "start_date": row.get("StartDate1"),
        "end_date": row.get("EndDate1"),
        "job_identification": row.get("JobIdentification"),
    }


class D365Facade:
    """Read-only client credentials OData; named lookups only."""

    def __init__(self, settings: Settings):
        self._s = settings
        self._env = settings.d365_environment_url.rstrip("/")
        self._data_area = settings.d365_default_data_area_id or ""
        tenant = settings.d365_tenant_id or settings.tenant_id
        self._authority = f"https://login.microsoftonline.com/{tenant}"

    def _is_configured(self) -> bool:
        return bool(self._s.d365_environment_url)

    def _resource(self) -> str:
        ax = self._env.split("//", 1)[-1].split("/", 1)[0]
        return f"https://{ax}"

    def _token(self) -> str:
        cid = self._s.d365_client_id
        sec = self._s.d365_client_secret
        if not (cid and sec and self._env):
            raise RuntimeError("D365 is not configured; set D365_* environment variables")

        app = msal.ConfidentialClientApplication(
            client_id=cid,
            authority=self._authority,
            client_credential=sec,
        )
        res = app.acquire_token_for_client(scopes=[self._resource() + "/.default"])
        if not res.get("access_token"):
            raise RuntimeError(res.get("error_description") or "D365 MSAL failure")
        return res["access_token"]

    def _odata_headers(self, token: str) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Prefer": 'odata.include-annotations="*"',
        }
        if self._data_area:
            h["Company"] = self._data_area
        return h

    @retry(wait=wait_exponential_jitter(initial=2, max=60), stop=stop_after_attempt(5), reraise=True)
    async def _get(self, relative_path_query: str) -> dict[str, Any]:
        token = self._token()
        url = f"{self._env}/{relative_path_query.lstrip('/')}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url, headers=self._odata_headers(token))
            if r.status_code == 429:
                logger.warning("D365 throttle 429 — retry via tenacity")
                r.raise_for_status()
            r.raise_for_status()
            return r.json()

    async def _gather_value_pages(self, relative_or_first_query: str, *, page_cap: int = 10) -> list[Any]:
        """Append **value[]** payloads while ``@odata.nextLink`` resolves (pagination helper)."""

        aggregated: list[Any] = []
        next_ref: str | None = relative_or_first_query
        async with httpx.AsyncClient(timeout=120.0) as client:
            for _ in range(page_cap):
                if not next_ref:
                    break
                token = self._token()
                url = (
                    next_ref
                    if str(next_ref).startswith("http")
                    else f"{self._env}/{str(next_ref).lstrip('/')}"
                )
                r = await client.get(url, headers=self._odata_headers(token))
                if r.status_code == 429:
                    r.raise_for_status()
                r.raise_for_status()
                blob = r.json()
                aggregated.extend(blob.get("value") or [])
                next_ref = blob.get("@odata.nextLink")
        return aggregated

    async def _query(self, entity: str, filter_expr: str, select_fields: str, top: int) -> list[Any]:
        path = _build_data_path(entity, filter_expr, select_fields, top)
        blob = await self._get(path)
        return list(blob.get("value") or [])

    def _format_result(
        self,
        rows: list[Any],
        mapper: Callable[[dict[str, Any]], dict[str, Any]],
        query: str,
        entity_label: str,
        *,
        multi: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not rows:
            return _not_found(query, entity_label)
        mapped = [mapper(r) for r in rows]
        if multi or len(mapped) > 1:
            payload: dict[str, Any] = {"found": True, "match_count": len(mapped), "results": mapped}
        else:
            payload = {"found": True, **mapped[0]}
        if extra:
            payload.update(extra)
        return payload

    def _error_response(self, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code in (401, 403):
                return {
                    "found": False,
                    "error": "auth_failed",
                    "message": "D365 authentication or authorization failed",
                }
            return {
                "found": False,
                "error": "upstream_unavailable",
                "message": f"D365 request failed with status {code}",
            }
        if isinstance(exc, RuntimeError):
            msg = str(exc)
            if "not configured" in msg.lower() or "msal" in msg.lower():
                return {"found": False, "error": "auth_failed", "message": "D365 authentication failed"}
        return {"found": False, "error": "upstream_unavailable", "message": "D365 lookup failed"}

    async def _run_lookup(self, coro_factory: Callable[[], Any]) -> str:
        try:
            result = await coro_factory()
            return _json_response(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("D365 lookup failed")
            return _json_response(self._error_response(exc))

    async def lookup_purchase_order(self, po_number: str) -> str:
        if not self._is_configured():
            return _json_response({"note": "stub", "po": po_number})

        async def _do() -> dict[str, Any]:
            key = _escape_odata(po_number.strip())
            filt = f"PurchaseOrderNumber eq '{key}'"
            rows = await self._query("PurchaseOrderHeadersV2", filt, _PO_SELECT, 1)
            return self._format_result(rows, _map_po, po_number, "purchase order")

        return await self._run_lookup(_do)

    async def lookup_vendor(self, account_or_name: str) -> str:
        if not self._is_configured():
            return _json_response({"note": "stub", "vendorLookup": account_or_name})

        async def _do() -> dict[str, Any]:
            raw = account_or_name.strip()
            key = _escape_odata(raw)
            if _RE_VENDOR_ACCOUNT.match(raw):
                filt = f"VendorAccountNumber eq '{key}'"
                top = 1
                multi = False
            else:
                filt = f"VendorOrganizationName eq '*{key}*'"
                top = 5
                multi = True
            rows = await self._query("VendorsV3", filt, _VENDOR_SELECT, top)
            return self._format_result(rows, _map_vendor, raw, "vendor", multi=multi)

        return await self._run_lookup(_do)

    async def lookup_customer(self, account_or_name: str) -> str:
        if not self._is_configured():
            return _json_response({"note": "stub", "customerLookup": account_or_name})

        async def _do() -> dict[str, Any]:
            raw = account_or_name.strip()
            key = _escape_odata(raw)
            if _RE_CUSTOMER_ACCOUNT.match(raw):
                filt = f"CustomerAccount eq '{key}'"
                top = 1
                multi = False
            else:
                filt = f"OrganizationName eq '*{key}*'"
                top = 5
                multi = True
            rows = await self._query("CustomersV3", filt, _CUSTOMER_SELECT, top)
            return self._format_result(rows, _map_customer, raw, "customer", multi=multi)

        return await self._run_lookup(_do)

    async def lookup_invoice_ap(self, number: str) -> str:
        if not self._is_configured():
            return _json_response({"note": "stub", "apInvoice": number})

        async def _do() -> dict[str, Any]:
            key = _escape_odata(number.strip())
            filt = f"InvoiceNumber eq '*{key}*'"
            rows = await self._query("VendorInvoiceHeaders", filt, _AP_INVOICE_SELECT, 1)
            return self._format_result(rows, _map_ap_invoice, number, "AP invoice")

        return await self._run_lookup(_do)

    async def lookup_invoice_ar(self, number: str) -> str:
        if not self._is_configured():
            return _json_response({"note": "stub", "arInvoice": number})

        async def _do() -> dict[str, Any]:
            raw = number.strip()
            key = _escape_odata(raw)
            if _RE_CUSTOMER_ACCOUNT.match(raw):
                filt = f"InvoiceCustomerAccountNumber eq '{key}'"
                top = 10
                multi = True
            else:
                filt = f"InvoiceNumber eq '{key}'"
                top = 1
                multi = False
            rows = await self._query("SalesInvoiceHeaders", filt, _AR_INVOICE_SELECT, top)
            return self._format_result(rows, _map_ar_invoice, raw, "AR invoice", multi=multi)

        return await self._run_lookup(_do)

    async def lookup_employee(self, query: str) -> str:
        if not self._is_configured():
            return _json_response({"note": "stub", "employeeQuery": query})

        async def _do() -> dict[str, Any]:
            raw = query.strip()
            key = _escape_odata(raw)
            active = "WorkerStatus eq Microsoft.Dynamics.DataEntities.HcmWorkerStatus'Employed'"
            if _RE_PERSONNEL.match(raw):
                filt = f"PersonnelNumber eq '{key}' and {active}"
                top = 1
                multi = False
            else:
                filt = f"Name eq '*{key}*' and {active}"
                top = 5
                multi = True
            rows = await self._query("Workers", filt, _WORKER_SELECT, top)
            result = self._format_result(
                rows,
                _map_worker,
                raw,
                "employee",
                multi=multi,
            )
            result["enrichment_only"] = True
            return result

        return await self._run_lookup(_do)

    async def lookup_project(self, project_key: str) -> str:
        if not self._is_configured():
            return _json_response({"note": "stub", "project": project_key})

        async def _do() -> dict[str, Any]:
            raw = project_key.strip()
            key = _escape_odata(raw)
            active = "Status eq Microsoft.Dynamics.DataEntities.PSAProjStatus'Active'"
            if _RE_PROJECT_ID.match(raw):
                filt = f"ProjectID eq '{key}' and {active}"
                top = 1
                multi = False
            else:
                filt = f"ProjectName eq '*{key}*' and {active}"
                top = 5
                multi = True
            rows = await self._query("Projects", filt, _PROJECT_SELECT, top)
            return self._format_result(rows, _map_project, raw, "project", multi=multi)

        return await self._run_lookup(_do)
