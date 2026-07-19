"""Bot Framework Connector — proactive messaging using stored ConversationReference (C03)."""

from __future__ import annotations

import logging

import httpx
from microsoft_teams.api import ConversationReference

from ltm.auth.tokens import acquire_bot_connector_token
from ltm.config.settings import Settings

logger = logging.getLogger(__name__)


def send_proactive_message_simple(
    ref: ConversationReference,
    *,
    text: str,
    adaptive_card_dict: dict | None,
    settings: Settings,
) -> None:
    """POST /v3/conversations/{{id}}/activities with a proactive message."""
    token = acquire_bot_connector_token(settings)

    svc = (ref.service_url or "").rstrip("/")
    conv_id = ref.conversation.id
    url = f"{svc}/v3/conversations/{conv_id}/activities"

    body: dict = {
        "type": "message",
        "serviceUrl": ref.service_url,
        "channelId": str(ref.channel_id),
        "from": {"id": ref.bot.id, "name": getattr(ref.bot, "name", None) or ""},
        "conversation": {
            "id": ref.conversation.id,
            "tenantId": ref.conversation.tenant_id,
            "conversationType": ref.conversation.conversation_type,
        },
        "text": text,
    }
    if ref.user:
        body["recipient"] = {"id": ref.user.id, "name": getattr(ref.user, "name", None) or ""}

    if adaptive_card_dict:
        body["attachments"] = [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": adaptive_card_dict,
            }
        ]

    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        json=body,
        timeout=60.0,
    )
    try:
        resp.raise_for_status()
    except Exception:
        logger.exception("Proactive Connector POST failed url=%s body_keys=%s", url, list(body.keys()))
        raise

