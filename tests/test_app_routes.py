from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_legal_health_and_protected_cron_routes(monkeypatch):
    monkeypatch.setenv("BOT_SKIP_AUTH", "true")
    entry = importlib.import_module("app")
    adapter = entry.app.server.adapter.app

    with TestClient(adapter) as client:
        assert client.get("/").status_code == 200
        assert client.get("/privacy").status_code == 200
        assert client.get("/terms").status_code == 200

        health = client.get("/health")
        assert health.status_code == 200
        payload = health.json()
        assert payload["status"] == "ok"
        assert payload["database"]["backend"] == "override"
        assert payload["llm"]["primary"]

        cron = client.post("/internal/cron/overdue")
        assert cron.status_code == 403
