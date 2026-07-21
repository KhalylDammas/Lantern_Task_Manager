"""Environment-driven settings (LTM_SYSTEM_SPEC §8, C08)."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ltm.config.env_loader import dotenv_paths, repo_root

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    return repo_root()


def config_dir() -> Path:
    """JSON artefacts ship under src/config for Azure zip-deploy."""
    bundled = Path(__file__).resolve().parents[2] / "config"
    if bundled.exists():
        return bundled
    return _repo_root() / "config"


_DOTENV_FILES = dotenv_paths()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        **({"env_file": _DOTENV_FILES} if _DOTENV_FILES else {}),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    port: int = Field(default_factory=lambda: int(os.environ.get("PORT", "3978")))

    client_id: str = Field(alias="CLIENT_ID", default="")
    client_secret: str = Field(alias="CLIENT_SECRET", default="")
    tenant_id: str = Field(alias="TENANT_ID", default="")
    bot_type: str = Field(alias="BOT_TYPE", default="")

    # SQL: ODBC driver connection string from Key Vault ref on Azure or .env locally
    azure_sql_odbc_connection_string: str = Field(alias="AZURE_SQL_ODBC_CONNECTION_STRING", default="")

    # Turso (C06 interim, remote-only): see docs/specs/2026-05-20-turso-database-design.md
    turso_database_url: str = Field(alias="TURSO_DATABASE_URL", default="")
    turso_auth_token: str = Field(alias="TURSO_AUTH_TOKEN", default="")

    llm_primary: Literal["anthropic", "openai", "azure_openai", "groq"] = Field(
        default="groq",
        alias="LLM_PRIMARY",
    )
    llm_tool_profile: Literal["full", "groq_chat"] = Field(
        default="full",
        alias="LLM_TOOL_PROFILE",
    )
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model_id: str = Field(default="claude-3-5-haiku-20241022", alias="ANTHROPIC_MODEL_ID")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    azure_openai_endpoint: str = Field(default="", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str = Field(default="", alias="AZURE_OPENAI_API_KEY")
    azure_openai_deployment: str = Field(default="", alias="AZURE_OPENAI_DEPLOYMENT_NAME")
    azure_openai_api_version: str = Field(default="2024-06-01", alias="AZURE_OPENAI_API_VERSION")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
    groq_fallback_model: str = Field(default="qwen/qwen3.6-27b", alias="GROQ_FALLBACK_MODEL")

    llm_rate_limit_rpm: int = Field(default=30, alias="LLM_RATE_LIMIT_RPM")
    llm_rate_limit_tpm: int = Field(default=7500, alias="LLM_RATE_LIMIT_TPM")
    llm_request_min_interval_ms: int = Field(default=0, alias="LLM_REQUEST_MIN_INTERVAL_MS")
    llm_daily_request_limit: int = Field(default=0, alias="LLM_DAILY_REQUEST_LIMIT")
    llm_daily_token_limit: int = Field(default=0, alias="LLM_DAILY_TOKEN_LIMIT")
    llm_request_timeout_seconds: float = Field(default=60.0, alias="LLM_REQUEST_TIMEOUT_SECONDS")
    llm_retry_max_attempts: int = Field(default=3, alias="LLM_RETRY_MAX_ATTEMPTS")
    llm_circuit_failure_threshold: int = Field(default=3, alias="LLM_CIRCUIT_FAILURE_THRESHOLD")
    llm_circuit_open_seconds: float = Field(default=60.0, alias="LLM_CIRCUIT_OPEN_SECONDS")
    llm_fallback_enabled: bool = Field(default=True, alias="LLM_FALLBACK_ENABLED")
    llm_governor_max_wait_seconds: float = Field(default=30.0, alias="LLM_GOVERNOR_MAX_WAIT_SECONDS")
    llm_memory_max_turns: int = Field(default=4, alias="LLM_MEMORY_MAX_TURNS")
    llm_memory_max_tool_result_chars: int = Field(default=6000, alias="LLM_MEMORY_MAX_TOOL_RESULT_CHARS")
    llm_memory_max_chars: int = Field(default=12000, alias="LLM_MEMORY_MAX_CHARS")
    llm_terminal_responses_enabled: bool = Field(default=True, alias="LLM_TERMINAL_RESPONSES_ENABLED")
    llm_dynamic_tools_enabled: bool = Field(default=True, alias="LLM_DYNAMIC_TOOLS_ENABLED")

    d365_environment_url: str = Field(default="", alias="D365_ENVIRONMENT_URL")
    d365_tenant_id: str = Field(default="", alias="D365_TENANT_ID")
    d365_client_id: str = Field(default="", alias="D365_CLIENT_ID")
    d365_client_secret: str = Field(default="", alias="D365_CLIENT_SECRET")
    d365_default_data_area_id: str = Field(default="", alias="D365_DATA_AREA_ID")

    primary_email_domain: str = Field(default="lanternsystems.com", alias="PRIMARY_EMAIL_DOMAIN")

    teams_app_id: str = Field(default="", alias="TEAMS_APP_ID")
    teams_app_tenant_id: str = Field(default="", alias="TEAMS_APP_TENANT_ID")
    notification_activity_enabled: bool = Field(default=True, alias="NOTIFICATION_ACTIVITY_ENABLED")
    notification_bot_dm_enabled: bool = Field(default=True, alias="NOTIFICATION_BOT_DM_ENABLED")
    verifier_mode: Literal["created_by", "manager_map", "graph_manager"] = Field(
        default="created_by",
        alias="LTM_VERIFIER_MODE",
    )
    cron_secret: str = Field(default="", alias="LTM_CRON_SECRET")

    def effective_groq_api_key(self) -> str:
        """Resolve Groq API key; warn when legacy OPENAI_API_KEY holds a gsk_ key."""
        explicit = (self.groq_api_key or "").strip()
        if explicit:
            return explicit
        legacy = (self.openai_api_key or "").strip()
        if legacy.startswith("gsk_"):
            logger.warning(
                "GROQ_API_KEY is unset but OPENAI_API_KEY looks like a Groq key (gsk_). "
                "Set GROQ_API_KEY explicitly; legacy fallback will be removed in a future release."
            )
            return legacy
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def clear_settings_cache() -> None:
    get_settings.cache_clear()
