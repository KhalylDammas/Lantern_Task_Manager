"""HTTP adapter that normalizes Teams activity payload quirks before SDK validation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from microsoft_teams.apps.http.fastapi_adapter import FastAPIAdapter
from microsoft_teams.apps.http.http_server import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

_SUPPORTED_ENTITY_TYPES = {
    "clientInfo",
    "mention",
    "https://schema.org/Message",
    "streaminfo",
    "ProductInfo",
}


def sanitize_activity_body(body: dict[str, Any]) -> dict[str, Any]:
    """Patch known Teams payload incompatibilities with microsoft-teams-apps 2.x."""

    sanitized = dict(body)
    activity_type = sanitized.get("type")

    if activity_type == "conversationUpdate" and not isinstance(sanitized.get("channelData"), dict):
        sanitized["channelData"] = {}

    entities = sanitized.get("entities")
    if isinstance(entities, list):
        sanitized["entities"] = [
            entity
            for entity in entities
            if isinstance(entity, dict) and entity.get("type") in _SUPPORTED_ENTITY_TYPES
        ]

    return sanitized


class SanitizingFastAPIAdapter(FastAPIAdapter):
    """FastAPI adapter that rewrites inbound activity bodies before App validation."""

    def register_route(self, method: str, path: str, handler) -> None:
        async def fastapi_handler(request: Request) -> Response:
            raw_body = await request.json()
            raw_entities = raw_body.get("entities") if isinstance(raw_body, dict) else None
            raw_entity_count = len(raw_entities) if isinstance(raw_entities, list) else 0
            body = sanitize_activity_body(raw_body)
            entities = body.get("entities") if isinstance(body, dict) else None
            entity_count = len(entities) if isinstance(entities, list) else 0
            headers = dict(request.headers)
            logger.info(
                "Inbound Teams HTTP request: method=%s path=%s activity_type=%s activity_id=%s "
                "conversation_id=%s raw_entities=%s sanitized_entities=%s auth_present=%s "
                "content_type=%s user_agent=%s",
                request.method,
                request.url.path,
                body.get("type"),
                body.get("id"),
                (body.get("conversation") or {}).get("id") if isinstance(body.get("conversation"), dict) else None,
                raw_entity_count,
                entity_count,
                bool(headers.get("authorization") or headers.get("Authorization")),
                headers.get("content-type"),
                headers.get("user-agent"),
            )
            http_request = HttpRequest(body=body, headers=headers)
            try:
                result: HttpResponse = await handler(http_request)
            except Exception:
                logger.exception(
                    "Inbound Teams HTTP request failed before response: activity_type=%s activity_id=%s",
                    body.get("type"),
                    body.get("id"),
                )
                raise
            status = result["status"]
            resp_body = result.get("body")
            logger.info(
                "Inbound Teams HTTP response: activity_type=%s activity_id=%s status=%s has_body=%s",
                body.get("type"),
                body.get("id"),
                status,
                resp_body is not None,
            )
            if resp_body is not None:
                return JSONResponse(content=resp_body, status_code=status)
            return Response(status_code=status)

        if method != "POST":
            raise ValueError(f"Unsupported HTTP method: {method}")
        self.app.post(path)(fastapi_handler)
