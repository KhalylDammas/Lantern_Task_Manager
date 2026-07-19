"""Bot Connector 1:1 delivery with create-conversation fallback."""

from __future__ import annotations

import logging

import httpx
from microsoft_teams.api import Account, ConversationAccount, ConversationReference

from ltm.auth.tokens import acquire_bot_connector_token, bot_connector_configured
from ltm.bot.proactive_connector import send_proactive_message_simple
from ltm.config.settings import Settings
from ltm.storage.conversation_bindings import ConversationBindingRepository

logger = logging.getLogger(__name__)

TEAMS_SERVICE_URL = "https://smba.trafficmanager.net/teams/"


def _teams_member_id(entra_object_id: str) -> str:
    oid = entra_object_id.strip()
    if oid.startswith("29:") or oid.startswith("28:"):
        return oid
    return f"29:{oid}"


def _bot_account(settings: Settings) -> Account:
    cid = (settings.client_id or "").strip()
    bot_id = cid if cid.startswith("28:") else f"28:{cid}"
    return Account(id=bot_id, name="Lantern Task Manager")


def create_personal_conversation_ref(
    settings: Settings,
    *,
    user_entra_id: str,
    user_display_name: str = "",
) -> ConversationReference | None:
    """Create a 1:1 Teams conversation when no binding exists."""
    if not bot_connector_configured(settings):
        return None

    tenant = (settings.teams_app_tenant_id or settings.tenant_id or "").strip()
    if not tenant:
        logger.warning("Cannot create conversation: tenant id missing")
        return None

    token = acquire_bot_connector_token(settings)
    member_id = _teams_member_id(user_entra_id)
    bot = _bot_account(settings)
    url = f"{TEAMS_SERVICE_URL.rstrip('/')}/v3/conversations"
    payload = {
        "bot": {"id": bot.id, "name": bot.name or ""},
        "members": [{"id": member_id, "name": user_display_name or ""}],
        "channelData": {"tenant": {"id": tenant}},
        "isGroup": False,
    }
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        conv_id = data.get("id")
        if not isinstance(conv_id, str) or not conv_id:
            logger.warning("Create conversation missing id: %s", data)
            return None
        user_account = Account(id=member_id, name=user_display_name or "", aad_object_id=user_entra_id)
        return ConversationReference(
            bot=bot,
            user=user_account,
            conversation=ConversationAccount(id=conv_id, conversation_type="personal", tenant_id=tenant),
            channel_id="msteams",
            service_url=TEAMS_SERVICE_URL,
        )
    except Exception:
        logger.exception("Create conversation failed user=%s", user_entra_id)
        return None


def send_bot_dm(
    settings: Settings,
    session,
    *,
    user_entra_id: str,
    user_display_name: str,
    text: str,
    adaptive_card_dict: dict | None,
) -> tuple[bool, str]:
    """Send proactive 1:1 message; create conversation if needed. Never raises."""
    if not settings.notification_bot_dm_enabled:
        return False, "bot_dm_disabled"
    if not bot_connector_configured(settings):
        return False, "bot_connector_not_configured"

    binder = ConversationBindingRepository(session)
    ref = binder.get_ref(user_entra_id)
    created = False
    if ref is None:
        ref = create_personal_conversation_ref(
            settings,
            user_entra_id=user_entra_id,
            user_display_name=user_display_name,
        )
        created = ref is not None

    if ref is None:
        return False, "no_conversation_ref"

    try:
        send_proactive_message_simple(ref, text=text, adaptive_card_dict=adaptive_card_dict, settings=settings)
        binder.upsert(user_entra_id, ref)
        return True, "created_and_sent" if created else "sent"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bot DM failed user=%s", user_entra_id)
        return False, str(exc)[:120]
