"""Unified Entra auth: MSI on Azure must enable Graph without CLIENT_SECRET."""

from __future__ import annotations

import pytest

from ltm.auth import tokens
from ltm.config.settings import Settings


@pytest.fixture(autouse=True)
def clean_auth_env(monkeypatch):
    for var in ("CLIENT_ID", "CLIENT_SECRET", "TENANT_ID", "BOT_TYPE"):
        monkeypatch.delenv(var, raising=False)


def make_settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_uses_managed_identity_detects_user_assigned_msi():
    assert tokens.uses_managed_identity(make_settings(BOT_TYPE="UserAssignedMsi"))
    assert tokens.uses_managed_identity(make_settings(BOT_TYPE="userassignedmsi"))
    assert tokens.uses_managed_identity(make_settings(BOT_TYPE=" UserAssignedMsi "))
    assert not tokens.uses_managed_identity(make_settings(BOT_TYPE=""))
    assert not tokens.uses_managed_identity(make_settings(BOT_TYPE="MultiTenant"))


def test_graph_configured_with_msi_and_no_secret():
    """The Azure regression: MSI deployments have no CLIENT_SECRET but Graph must be on."""
    s = make_settings(BOT_TYPE="UserAssignedMsi", CLIENT_ID="app-client-id")
    assert tokens.graph_configured(s)
    assert tokens.auth_mode(s) == "msi"


def test_graph_configured_with_client_secret_locally():
    s = make_settings(CLIENT_ID="cid", CLIENT_SECRET="secret", TENANT_ID="tid")
    assert tokens.graph_configured(s)
    assert tokens.auth_mode(s) == "client_secret"


def test_graph_not_configured_without_credentials():
    assert not tokens.graph_configured(make_settings())
    assert not tokens.graph_configured(make_settings(CLIENT_ID="cid"))
    # Secret without tenant cannot build an MSAL authority.
    assert not tokens.graph_configured(make_settings(CLIENT_ID="cid", CLIENT_SECRET="secret"))
    assert tokens.auth_mode(make_settings()) == "none"


def test_bot_connector_configured_mirrors_modes():
    assert tokens.bot_connector_configured(make_settings(BOT_TYPE="UserAssignedMsi", CLIENT_ID="cid"))
    assert tokens.bot_connector_configured(make_settings(CLIENT_ID="cid", CLIENT_SECRET="secret"))
    assert not tokens.bot_connector_configured(make_settings(CLIENT_ID="cid"))
    assert not tokens.bot_connector_configured(make_settings())


def test_acquire_graph_token_uses_msi(monkeypatch):
    captured: dict = {}

    class FakeToken:
        token = "msi-token"

    class FakeCredential:
        def __init__(self, client_id):
            captured["client_id"] = client_id

        def get_token(self, scope):
            captured["scope"] = scope
            return FakeToken()

    monkeypatch.setattr(tokens, "ManagedIdentityCredential", FakeCredential)
    s = make_settings(BOT_TYPE="UserAssignedMsi", CLIENT_ID="msi-client")
    assert tokens.acquire_graph_token(s) == "msi-token"
    assert captured == {"client_id": "msi-client", "scope": tokens.GRAPH_SCOPE}


def test_acquire_graph_token_uses_client_secret(monkeypatch):
    captured: dict = {}

    class FakeApp:
        def __init__(self, client_id, authority, client_credential):
            captured["client_id"] = client_id
            captured["authority"] = authority
            captured["client_credential"] = client_credential

        def acquire_token_for_client(self, scopes):
            captured["scopes"] = scopes
            return {"access_token": "secret-token"}

    monkeypatch.setattr(tokens, "ConfidentialClientApplication", FakeApp)
    s = make_settings(CLIENT_ID="cid", CLIENT_SECRET="shh", TENANT_ID="tid")
    assert tokens.acquire_graph_token(s) == "secret-token"
    assert captured["client_id"] == "cid"
    assert captured["client_credential"] == "shh"
    assert captured["authority"].endswith("/tid")
    assert captured["scopes"] == [tokens.GRAPH_SCOPE]


def test_acquire_graph_token_unconfigured_raises():
    with pytest.raises(RuntimeError, match="Graph auth not configured"):
        tokens.acquire_graph_token(make_settings())


def test_acquire_bot_connector_token_uses_msi(monkeypatch):
    captured: dict = {}

    class FakeToken:
        token = "connector-token"

    class FakeCredential:
        def __init__(self, client_id):
            captured["client_id"] = client_id

        def get_token(self, scope):
            captured["scope"] = scope
            return FakeToken()

    monkeypatch.setattr(tokens, "ManagedIdentityCredential", FakeCredential)
    s = make_settings(BOT_TYPE="UserAssignedMsi", CLIENT_ID="msi-client")
    assert tokens.acquire_bot_connector_token(s) == "connector-token"
    assert captured["scope"] == tokens.BOT_CONNECTOR_SCOPE


def test_verify_graph_access_unconfigured_reports_not_ok():
    ok, mode, detail = tokens.verify_graph_access(make_settings())
    assert ok is False
    assert mode == "none"
    assert "not configured" in detail


def test_graph_token_diagnostics_empty_roles():
    # JWT payload: {"appid":"msi-id","roles":[]}
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"appid": "msi-id", "roles": []}).encode()).decode().rstrip("=")
    token = f"header.{payload}.sig"
    diag = tokens.graph_token_diagnostics(token, expected_client_id="msi-id")
    assert "roles=[]" in diag or "roles claim is empty" in diag


def test_graph_token_diagnostics_with_user_read_all():
    import base64
    import json

    payload = base64.urlsafe_b64encode(
        json.dumps({"appid": "msi-id", "roles": ["User.Read.All"]}).encode()
    ).decode().rstrip("=")
    token = f"header.{payload}.sig"
    diag = tokens.graph_token_diagnostics(token, expected_client_id="msi-id")
    assert "User.Read.All" in diag
    assert "roles claim is empty" not in diag
