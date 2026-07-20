"""Startup diagnostics kept outside the Teams activity entrypoint."""

from __future__ import annotations

import logging
import os

from ltm.bot.http_routes import graph_health
from ltm.config.settings import get_settings

logger = logging.getLogger(__name__)


def log_startup_probes() -> None:
    settings = get_settings()
    ok, mode, detail = graph_health(force=True)
    if ok:
        logger.info("Startup Graph probe OK: mode=%s", mode)
    elif os.environ.get("TEAMSFX_ENV", "").strip().lower() == "playground":
        logger.info("Startup Graph probe skipped in Playground: %s", detail)
    else:
        logger.error(
            "Startup Graph probe FAILED (CLIENT_ID=%s, mode=%s): %s — mention resolution and /who are degraded.",
            settings.client_id,
            mode,
            detail,
        )

    if settings.d365_environment_url.strip():
        logger.info(
            "Startup D365 probe OK: environment=%s data_area=%s client_id=%s",
            settings.d365_environment_url,
            settings.d365_default_data_area_id or "(none)",
            settings.d365_client_id or "(unset)",
        )
    elif settings.llm_tool_profile == "full":
        logger.error("Startup D365 probe FAILED: D365_ENVIRONMENT_URL is unset.")
    else:
        logger.info("Startup D365 probe skipped (LLM_TOOL_PROFILE=%s)", settings.llm_tool_profile)
