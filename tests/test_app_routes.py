from __future__ import annotations

import importlib

import pytest


@pytest.mark.asyncio
async def test_legal_health_and_protected_cron_routes(monkeypatch):
    monkeypatch.setenv("BOT_SKIP_AUTH", "true")
    monkeypatch.setattr("ltm.bot.startup.log_startup_probes", lambda: None)
    monkeypatch.setattr(
        "ltm.bot.http_routes.graph_health",
        lambda: (True, "test", "Graph probe disabled in route test"),
    )
    monkeypatch.setattr(
        "ltm.bot.http_routes.database_health",
        lambda: (True, "override", "Database probe disabled in route test"),
    )
    monkeypatch.setattr(
        "ltm.bot.http_routes.llm_health_snapshot",
        lambda: {"ok": True, "primary": "test-model"},
    )
    entry = importlib.import_module("app")
    adapter = entry.app.server.adapter.app

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr("ltm.bot.http_routes.asyncio.to_thread", run_inline)

    endpoints = {route.path: route.endpoint for route in adapter.routes if hasattr(route, "endpoint")}
    assert (await endpoints["/"]()).status_code == 200
    assert (await endpoints["/privacy"]()).status_code == 200
    assert (await endpoints["/terms"]()).status_code == 200

    health = await endpoints["/health"]()
    assert health.status_code == 200
    payload = health.body.decode()
    assert '"status":"ok"' in payload
    assert '"backend":"override"' in payload
    assert '"primary":"test-model"' in payload

    cron = await endpoints["/internal/cron/overdue"](None)
    assert cron.status_code == 403
