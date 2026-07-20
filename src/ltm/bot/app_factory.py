"""Microsoft Teams SDK application construction and local-auth compatibility."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from azure.identity import ManagedIdentityCredential
from microsoft_teams.api.auth.json_web_token import JsonWebToken
from microsoft_teams.api.clients.user.token_client import UserTokenClient
from microsoft_teams.apps import App
from microsoft_teams.apps.token_manager import TokenManager
from microsoft_teams.common.http import ClientOptions

from ltm.bot.http_adapter import SanitizingFastAPIAdapter
from ltm.config.settings import Settings

logger = logging.getLogger(__name__)
_local_bot_token: JsonWebToken | None = None


def _token_factory(settings: Settings):
    def get_token(scopes, tenant_id=None):
        credential = ManagedIdentityCredential(client_id=settings.client_id)
        scopes_list = [scopes] if isinstance(scopes, str) else list(scopes)
        return credential.get_token(*scopes_list).token

    return get_token


def _install_local_auth(settings: Settings, *, http_timeout: float) -> None:
    async def local_bot_connector_token(self: TokenManager) -> JsonWebToken:
        global _local_bot_token
        if _local_bot_token and not _local_bot_token.is_expired():
            return _local_bot_token

        data = {
            "grant_type": "client_credentials",
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "scope": "https://api.botframework.com/.default",
        }
        tenant_ids = [value for value in (settings.tenant_id, "botframework.com") if value]
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(http_timeout)) as client:
            for tenant_id in tenant_ids:
                url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
                try:
                    response = await client.post(url, data=data)
                    response.raise_for_status()
                    token = response.json().get("access_token")
                    if isinstance(token, str) and token:
                        _local_bot_token = JsonWebToken(token)
                        return _local_bot_token
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning("Local Bot Connector token failed for tenant=%s: %s", tenant_id, exc)
        raise RuntimeError("Local Bot Connector token acquisition failed") from last_error

    async def skip_user_token_lookup(self: UserTokenClient, params: Any) -> Any:
        raise RuntimeError("User token lookup disabled for local preview")

    TokenManager.get_bot_token = local_bot_connector_token
    UserTokenClient.get = skip_user_token_lookup


def create_teams_app(
    settings: Settings,
    *,
    skip_auth: bool,
    http_timeout: float,
) -> App:
    if skip_auth:
        _install_local_auth(settings, http_timeout=http_timeout)
    return App(
        token=_token_factory(settings) if settings.bot_type == "UserAssignedMsi" else None,
        client=ClientOptions(timeout=http_timeout),
        http_server_adapter=SanitizingFastAPIAdapter(),
        skip_auth=skip_auth,
    )
