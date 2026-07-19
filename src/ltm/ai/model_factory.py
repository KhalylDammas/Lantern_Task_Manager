"""Select LLM implementation (LTM_SYSTEM_SPEC §10, C09)."""

from __future__ import annotations

import logging

from microsoft_teams.ai import AIModel
from microsoft_teams.openai import OpenAICompletionsAIModel

try:
    from ltm.ai.anthropic_teams_ai import AnthropicTeamsAIModel
except ImportError:
    AnthropicTeamsAIModel = None  # type: ignore[misc,assignment]

from ltm.ai.gateway import build_resilient_groq_model
from ltm.config.settings import Settings

logger = logging.getLogger(__name__)


def build_ai_model(settings: Settings) -> AIModel:
    """Return the configured primary LLM implementation."""

    if settings.llm_primary == "groq":
        return build_resilient_groq_model(settings)

    if settings.llm_primary == "anthropic":
        if AnthropicTeamsAIModel and settings.anthropic_api_key:
            return AnthropicTeamsAIModel(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model_id,
            )
        raise ValueError("ANTHROPIC_API_KEY is required when LLM_PRIMARY=anthropic")

    if settings.llm_primary == "azure_openai" or settings.azure_openai_endpoint:
        return OpenAICompletionsAIModel(
            model=settings.azure_openai_deployment or settings.openai_model,
            key=settings.azure_openai_api_key or settings.openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint or None,
            api_version=settings.azure_openai_api_version or None,
        )

    if settings.llm_primary == "openai":
        if not (settings.openai_api_key or "").strip():
            raise ValueError("OPENAI_API_KEY is required when LLM_PRIMARY=openai")
        return OpenAICompletionsAIModel(model=settings.openai_model, key=settings.openai_api_key)

    raise ValueError(f"Unsupported LLM_PRIMARY={settings.llm_primary!r}")
