"""LLM bindings for guarded, read-only D365 lookups."""

from __future__ import annotations

import logging
from typing import Any

from microsoft_teams.ai import Function
from pydantic import BaseModel

from ltm.config.settings import get_settings
from ltm.d365.facade import D365Facade

logger = logging.getLogger(__name__)


class POParams(BaseModel):
    po_number: str


class VendorParams(BaseModel):
    account_or_name: str


class CustomerParams(BaseModel):
    account_or_name: str


class APInvoiceParams(BaseModel):
    invoice_number: str


class ARInvoiceParams(BaseModel):
    invoice_number: str


class EmployeeParams(BaseModel):
    query: str


class ProjectParams(BaseModel):
    project_key: str


def _facade() -> D365Facade:
    return D365Facade(get_settings())


def _logged(tool_name: str, params: BaseModel, result: str) -> str:
    logger.info(
        "D365 tool completed: tool=%s parameter_fields=%s result_length=%s",
        tool_name,
        sorted(params.model_fields_set),
        len(result),
    )
    return result


async def query_po(params: POParams) -> str:
    return _logged("query_d365_po", params, await _facade().lookup_purchase_order(params.po_number))


async def query_vendor(params: VendorParams) -> str:
    return _logged("query_d365_vendor", params, await _facade().lookup_vendor(params.account_or_name))


async def query_customer(params: CustomerParams) -> str:
    return _logged("query_d365_customer", params, await _facade().lookup_customer(params.account_or_name))


async def query_ap_invoice(params: APInvoiceParams) -> str:
    return _logged("query_d365_invoice_ap", params, await _facade().lookup_invoice_ap(params.invoice_number))


async def query_ar_invoice(params: ARInvoiceParams) -> str:
    return _logged("query_d365_invoice_ar", params, await _facade().lookup_invoice_ar(params.invoice_number))


async def query_employee(params: EmployeeParams) -> str:
    return _logged("query_d365_employee", params, await _facade().lookup_employee(params.query))


async def query_project(params: ProjectParams) -> str:
    return _logged("query_d365_project", params, await _facade().lookup_project(params.project_key))


def build_d365_functions() -> list[Function[Any]]:
    definitions = (
        ("query_d365_po", "Read-only PO lookup.", POParams, query_po),
        ("query_d365_vendor", "Read-only vendor lookup.", VendorParams, query_vendor),
        ("query_d365_customer", "Read-only customer lookup.", CustomerParams, query_customer),
        ("query_d365_invoice_ap", "Read-only AP invoice lookup.", APInvoiceParams, query_ap_invoice),
        ("query_d365_invoice_ar", "Read-only AR invoice lookup.", ARInvoiceParams, query_ar_invoice),
        ("query_d365_employee", "Optional worker enrichment lookup.", EmployeeParams, query_employee),
        ("query_d365_project", "Read-only project lookup.", ProjectParams, query_project),
    )
    return [
        Function(name=name, description=description, parameter_schema=schema, handler=handler)
        for name, description, schema, handler in definitions
    ]
