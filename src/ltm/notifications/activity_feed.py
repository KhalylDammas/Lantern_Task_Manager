"""Microsoft Graph Teams activity feed notifications."""

from __future__ import annotations

import logging

import httpx

from ltm.auth.tokens import acquire_graph_token, graph_configured
from ltm.config.settings import Settings

logger = logging.getLogger(__name__)


def _entity_web_url(settings: Settings) -> str:
    app_id = (settings.teams_app_id or settings.client_id or "").strip()
    tenant = (settings.teams_app_tenant_id or settings.tenant_id or "").strip()
    if app_id and tenant:
        return f"https://teams.microsoft.com/l/entity/{app_id}/0?tenantId={tenant}"
    if app_id:
        return f"https://teams.microsoft.com/l/entity/{app_id}/0"
    return "https://teams.microsoft.com/"


def send_activity_notification(
    settings: Settings,
    *,
    user_entra_id: str,
    activity_type: str,
    preview_text: str,
    topic_title: str = "Lantern Task Manager",
) -> tuple[bool, str]:
    """POST /users/{id}/teamwork/sendActivityNotification. Never raises."""
    if not settings.notification_activity_enabled:
        return False, "activity_disabled"
    if not graph_configured(settings):
        return False, "graph_not_configured"
    if not (settings.teams_app_id or "").strip():
        return False, "teams_app_id_missing"

    url = f"https://graph.microsoft.com/v1.0/users/{user_entra_id}/teamwork/sendActivityNotification"
    body = {
        "topic": {
            "source": "text",
            "value": topic_title,
            "webUrl": _entity_web_url(settings),
        },
        "activityType": activity_type,
        "previewText": {"content": preview_text[:150]},
    }
    try:
        token = acquire_graph_token(settings)
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.warning(
                "Activity notification failed user=%s type=%s status=%s body=%s",
                user_entra_id,
                activity_type,
                resp.status_code,
                resp.text[:200],
            )
            return False, f"http_{resp.status_code}"
        return True, "sent"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Activity notification error user=%s type=%s", user_entra_id, activity_type)
        return False, str(exc)[:120]
