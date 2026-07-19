"""Unified Entra token acquisition for Graph and Bot Connector (C03/C08).

Two auth modes, selected by deployment shape:

- ``msi`` — Azure App Service / Functions with a UserAssigned managed identity
  (``BOT_TYPE=UserAssignedMsi``, no ``CLIENT_SECRET`` app setting).
- ``client_secret`` — local F5 / Playground where the Toolkit writes
  ``CLIENT_ID`` / ``CLIENT_SECRET`` / ``TENANT_ID`` into the environment.

All Graph and proactive Bot Connector callers must come through here so a
missing secret on Azure can never silently disable Graph again.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from azure.identity import ManagedIdentityCredential
from msal import ConfidentialClientApplication

from ltm.config.settings import Settings

logger = logging.getLogger(__name__)

GRAPH_SCOPE = "https://graph.microsoft.com/.default"
BOT_CONNECTOR_SCOPE = "https://api.botframework.com/.default"
# Microsoft Graph application permission (not delegated) for directory user read/search.
GRAPH_USER_READ_ALL_ROLE_ID = "df021288-bdef-4463-88db-98f22de91432"
GRAPH_REQUIRED_APP_ROLES = frozenset({"User.Read.All"})

_MODE_LOGGED: set[str] = set()


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode JWT payload for diagnostics only (signature not verified)."""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    segment = parts[1]
    padded = segment + "=" * (-len(segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
        data = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def graph_token_diagnostics(token: str, *, expected_client_id: str = "") -> str:
    """Human-readable summary of app-only Graph token claims (no token value logged)."""
    payload = _decode_jwt_payload(token)
    if not payload:
        return "Could not decode Graph token payload."

    roles = payload.get("roles") or []
    if not isinstance(roles, list):
        roles = []
    role_names = [str(r) for r in roles]
    app_id = str(payload.get("appid") or payload.get("azp") or "")
    oid = str(payload.get("oid") or "")

    lines = [
        f"token appid={app_id or 'unknown'}",
        f"token oid={oid or 'unknown'}",
        f"token roles={role_names or '[]'}",
    ]
    if expected_client_id and app_id and app_id.lower() != expected_client_id.lower():
        lines.append(
            f"token appid mismatch: expected CLIENT_ID={expected_client_id} "
            f"but token was issued for {app_id}"
        )
    if not role_names:
        lines.append(
            "roles claim is empty — the Entra app backing this identity has no granted "
            "Microsoft Graph *application* permissions (delegated permissions do not appear "
            "in roles). Grant User.Read.All (Application) on the Managed Identity app "
            f"registration whose Application (client) ID is {expected_client_id or app_id}, "
            "then admin-consent. Permissions on a separate local Toolkit bot app do not apply."
        )
    elif not GRAPH_REQUIRED_APP_ROLES.intersection(role_names):
        lines.append(
            f"token is missing required Graph application roles "
            f"{sorted(GRAPH_REQUIRED_APP_ROLES)}; has {role_names}"
        )
    return "; ".join(lines)


def uses_managed_identity(settings: Settings) -> bool:
    """True when running with a UserAssigned managed identity (Azure provision)."""
    return (settings.bot_type or "").strip().lower() == "userassignedmsi"


def auth_mode(settings: Settings) -> str:
    """``msi`` | ``client_secret`` | ``none`` — how Entra tokens would be acquired."""
    if uses_managed_identity(settings):
        return "msi"
    if settings.client_id and settings.client_secret:
        return "client_secret"
    return "none"


def bot_connector_configured(settings: Settings) -> bool:
    """Proactive Bot Connector auth is possible: MSI on Azure, or client secret locally."""
    if not settings.client_id:
        return False
    return uses_managed_identity(settings) or bool(settings.client_secret)


def graph_configured(settings: Settings) -> bool:
    """Graph app-only auth is possible: MSI on Azure, or client secret locally.

    Deliberately does NOT require ``CLIENT_SECRET`` — that requirement is what
    silently disabled Graph on the MSI-based Azure deployment.
    """
    if not settings.client_id:
        return False
    if uses_managed_identity(settings):
        return True
    return bool(settings.client_secret and settings.tenant_id)


def _log_mode_once(purpose: str, mode: str) -> None:
    key = f"{purpose}:{mode}"
    if key not in _MODE_LOGGED:
        _MODE_LOGGED.add(key)
        logger.info("Entra token mode for %s: %s", purpose, mode)


def _msi_token(settings: Settings, scope: str) -> str:
    credential = ManagedIdentityCredential(client_id=settings.client_id)
    return credential.get_token(scope).token


def _client_secret_token(settings: Settings, scope: str) -> str:
    app = ConfidentialClientApplication(
        client_id=settings.client_id,
        authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
        client_credential=settings.client_secret,
    )
    result = app.acquire_token_for_client(scopes=[scope])
    token = result.get("access_token")
    if not token:
        raise RuntimeError(result.get("error_description") or f"Token acquisition failed for {scope}")
    return token


def acquire_graph_token(settings: Settings) -> str:
    """App-only Graph token via MSI (Azure) or client credentials (local)."""
    if uses_managed_identity(settings):
        _log_mode_once("graph", "msi")
        return _msi_token(settings, GRAPH_SCOPE)
    if settings.client_secret:
        _log_mode_once("graph", "client_secret")
        return _client_secret_token(settings, GRAPH_SCOPE)
    raise RuntimeError(
        "Graph auth not configured: need BOT_TYPE=UserAssignedMsi (Azure MSI) "
        "or CLIENT_ID/CLIENT_SECRET/TENANT_ID (local client credentials)."
    )


def acquire_bot_connector_token(settings: Settings) -> str:
    """Bot Connector token for proactive sends via the same MSI/secret split."""
    if uses_managed_identity(settings):
        _log_mode_once("bot_connector", "msi")
        return _msi_token(settings, BOT_CONNECTOR_SCOPE)
    if settings.client_id and settings.client_secret:
        _log_mode_once("bot_connector", "client_secret")
        return _client_secret_bot_connector_token(settings)
    raise RuntimeError(
        "Bot Connector auth not configured: need BOT_TYPE=UserAssignedMsi (Azure MSI) "
        "or CLIENT_ID/CLIENT_SECRET (local client credentials)."
    )


def _client_secret_bot_connector_token(settings: Settings) -> str:
    """Client-credentials Connector token (single- then multi-tenant authority)."""
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "scope": BOT_CONNECTOR_SCOPE,
    }
    urls: list[str] = []
    if settings.tenant_id:
        urls.append(f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/token")
    urls.append("https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token")

    last_err: Exception | None = None
    for url in urls:
        try:
            r = httpx.post(url, data=data, timeout=30.0)
            r.raise_for_status()
            tok = r.json().get("access_token")
            if isinstance(tok, str) and tok:
                return tok
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"Bot Connector token acquisition failed after {urls!r}") from last_err


def verify_graph_access(settings: Settings) -> tuple[bool, str, str]:
    """Acquire a Graph token and probe ``GET /v1.0/users?$top=1``.

    Returns ``(ok, mode, detail)`` for startup logging and the /health route.
    Never raises.
    """
    mode = auth_mode(settings)
    if not graph_configured(settings):
        return False, mode, (
            "Graph not configured: set BOT_TYPE=UserAssignedMsi with CLIENT_ID (Azure) "
            "or CLIENT_ID/CLIENT_SECRET/TENANT_ID (local)."
        )
    try:
        token = acquire_graph_token(settings)
    except Exception as exc:  # noqa: BLE001
        return False, mode, f"Graph token acquisition failed: {exc}"

    try:
        r = httpx.get(
            "https://graph.microsoft.com/v1.0/users?$top=1&$select=id",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
    except Exception as exc:  # noqa: BLE001
        return False, mode, f"Graph probe request failed: {exc}"

    if r.status_code >= 400:
        token_diag = graph_token_diagnostics(token, expected_client_id=settings.client_id)
        return False, mode, (
            f"Graph probe returned {r.status_code} for CLIENT_ID={settings.client_id}. "
            f"{token_diag} "
            f"Grant User.Read.All as an *Application* permission (not Delegated) on that app, "
            f"then admin-consent. Run: scripts/grant_msi_graph_permissions.sh {settings.client_id}. "
            f"Graph body: {r.text[:200]}"
        )
    return True, mode, "Graph reachable"
