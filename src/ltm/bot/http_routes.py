"""Non-Bot HTTP routes exposed by the LTM host."""

from __future__ import annotations

import asyncio
import hmac
import time
from pathlib import Path

from fastapi import Header, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text as sa_text

from ltm.ai.gateway import llm_health_snapshot
from ltm.auth.tokens import verify_graph_access
from ltm.config.settings import get_settings
from ltm.notifications.scheduled_jobs import run_daily_summary, run_notification_retry, run_overdue_refresh_and_notify
from ltm.storage.db import session_scope

_GRAPH_HEALTH_CACHE_SECONDS = 300.0
_graph_health_cache: tuple[float, bool, str, str] | None = None


def graph_health(force: bool = False) -> tuple[bool, str, str]:
    global _graph_health_cache
    now = time.monotonic()
    if not force and _graph_health_cache is not None:
        cached_at, ok, mode, detail = _graph_health_cache
        if now - cached_at < _GRAPH_HEALTH_CACHE_SECONDS:
            return ok, mode, detail
    ok, mode, detail = verify_graph_access(get_settings())
    _graph_health_cache = (now, ok, mode, detail)
    return ok, mode, detail


def database_health() -> tuple[bool, str, str]:
    try:
        from ltm.storage.engine_config import build_engine_config

        backend = build_engine_config().backend
        with session_scope() as session:
            session.execute(sa_text("SELECT 1"))
        return True, backend, "Database reachable"
    except Exception as exc:  # noqa: BLE001
        return False, "", f"Database check failed: {exc}"


def attach_http_routes(adapter, legal_dir: Path) -> None:
    """Attach legal, health, and protected scheduler routes to FastAPI."""

    def cron_authorized(secret_header: str | None) -> bool:
        expected = (get_settings().cron_secret or "").strip()
        supplied = (secret_header or "").strip()
        return bool(expected and supplied) and hmac.compare_digest(supplied, expected)

    def legal_page(filename: str) -> str:
        return (legal_dir / filename).read_text(encoding="utf-8")

    @adapter.get("/")
    async def legal_home():
        return HTMLResponse(content=legal_page("index.html"))

    @adapter.get("/privacy")
    async def legal_privacy():
        return HTMLResponse(content=legal_page("privacy.html"))

    @adapter.get("/terms")
    async def legal_terms():
        return HTMLResponse(content=legal_page("terms.html"))

    @adapter.get("/health")
    async def health():
        graph_ok, graph_mode, graph_detail = await asyncio.to_thread(graph_health)
        db_ok, db_backend, db_detail = await asyncio.to_thread(database_health)
        llm = await asyncio.to_thread(llm_health_snapshot)
        payload = {
            "status": "ok" if db_ok else "degraded",
            "program": "ltm",
            "graph": {"ok": graph_ok, "mode": graph_mode, "detail": graph_detail},
            "database": {"ok": db_ok, "backend": db_backend, "detail": db_detail},
            "llm": llm,
        }
        return JSONResponse(content=payload, status_code=200 if db_ok else 503)

    @adapter.post("/internal/cron/overdue")
    async def cron_overdue(x_ltm_cron_secret: str | None = Header(default=None, alias="X-LTM-Cron-Secret")):
        if not cron_authorized(x_ltm_cron_secret):
            return JSONResponse({"error": "cron disabled or unauthorized"}, status_code=403)
        stats = await asyncio.to_thread(run_overdue_refresh_and_notify)
        return JSONResponse({"ok": True, "stats": stats})

    @adapter.post("/internal/cron/daily-summary")
    async def cron_daily_summary(
        assignee_entra_id: str | None = Query(default=None),
        force: bool = Query(default=False),
        x_ltm_cron_secret: str | None = Header(default=None, alias="X-LTM-Cron-Secret"),
    ):
        if not cron_authorized(x_ltm_cron_secret):
            return JSONResponse({"error": "cron disabled or unauthorized"}, status_code=403)
        if force and not assignee_entra_id:
            return JSONResponse({"error": "force requires assignee_entra_id for a single-user test send"}, status_code=400)
        stats = await asyncio.to_thread(run_daily_summary, assignee_entra_id=assignee_entra_id, force=force)
        return JSONResponse({"ok": True, "stats": stats})

    @adapter.post("/internal/cron/notification-retry")
    async def cron_notification_retry(x_ltm_cron_secret: str | None = Header(default=None, alias="X-LTM-Cron-Secret")):
        if not cron_authorized(x_ltm_cron_secret):
            return JSONResponse({"error": "cron disabled or unauthorized"}, status_code=403)
        stats = await asyncio.to_thread(run_notification_retry)
        return JSONResponse({"ok": True, "stats": stats})
