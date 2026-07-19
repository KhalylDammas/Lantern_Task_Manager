import os

from ltm.config.env_loader import load_project_dotenv
from ltm.config.settings import clear_settings_cache

# Toolkit debug uses cwd `src/`; load every env file the app expects before Settings is cached.
load_project_dotenv(override=True)
clear_settings_cache()


class Config:
    """Process / Teams Toolkit environment (MSI vs local secrets)."""

    PORT = int(os.environ.get("PORT", "3978"))
    APP_ID = os.environ.get("CLIENT_ID", "")
    APP_PASSWORD = os.environ.get("CLIENT_SECRET", "")
    APP_TYPE = os.environ.get("BOT_TYPE", "")
    APP_TENANTID = os.environ.get("TENANT_ID", "")
    # Optional when using Anthropic / Azure OpenAI / Groq only:
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
