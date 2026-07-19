"""Microsoft Graph helpers (C03) and org mapping for manager resolution.

Proactive Bot Connector delivery (after persisting a ConversationReference) lives in
``ltm.bot.proactive_connector``.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from ltm.auth.tokens import acquire_graph_token
from ltm.config.settings import Settings

logger = logging.getLogger(__name__)


def _escape_graph_search_term(query: str) -> str:
    return query.strip().replace("\\", "\\\\").replace('"', '\\"')


class GraphClient:
    """App-only Graph client (managed identity on Azure, client credentials locally)."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def _token(self) -> str:
        return acquire_graph_token(self._settings)

    async def search_users(self, query: str, top: int = 8) -> list[dict[str, Any]]:
        """$search requires ConsistencyLevel: eventual."""
        search_term = _escape_graph_search_term(query)
        if not search_term:
            return []

        token = self._token()
        params = urlencode(
            {
                "$search": f'"displayName:{search_term}" OR "mail:{search_term}"',
                "$select": "id,displayName,mail,userPrincipalName,department,jobTitle",
                "$top": str(top),
            }
        )
        url = f"https://graph.microsoft.com/v1.0/users?{params}"

        headers = {"Authorization": f"Bearer {token}", "ConsistencyLevel": "eventual"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code >= 400:
                logger.warning("Graph user search failed: %s %s", r.status_code, r.text)
                return []

            data = r.json()
            users = []
            for u in data.get("value", [])[:top]:
                users.append(
                    {
                        "entra_object_id": u["id"],
                        "display_name": u.get("displayName") or "",
                        "upn": u.get("userPrincipalName") or "",
                        "mail": u.get("mail") or "",
                        "department": u.get("department") or "",
                        "job_title": u.get("jobTitle") or "",
                    }
                )
            logger.info("Graph user search for '%s' returned %d results", query, len(users))
            if len(users) <= 3:
                logger.info("Users found %s results", json.dumps(users, indent=4))
            return users

    async def get_manager_entra_id(self, user_id: str) -> str | None:
        """Return the Entra object id of the user's manager, if Graph exposes one."""
        oid = (user_id or "").strip()
        if not oid:
            return None

        token = self._token()
        url = f"https://graph.microsoft.com/v1.0/users/{oid}/manager?$select=id"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 404:
                return None
            if r.status_code >= 400:
                logger.warning("Graph manager lookup failed for %s: %s %s", oid, r.status_code, r.text)
                return None
            data = r.json()
            manager_id = data.get("id")
            return str(manager_id) if manager_id else None


def manager_for_assignee(assignee_entra_id: str) -> str | None:
    """Resolve manager Entra object id from manager_map.json."""
    from ltm.config.artefacts import load_manager_map

    data = load_manager_map()
    return (data.get("managers_by_assignee_entra_id") or {}).get(assignee_entra_id)
