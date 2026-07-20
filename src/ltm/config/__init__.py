"""Configuration loading (environment and typed settings)."""

from ltm.config.env_loader import load_project_dotenv
from ltm.config.settings import Settings, clear_settings_cache, get_settings


def initialize_settings() -> Settings:
    """Load Toolkit dotenv files, then return the single typed settings model."""
    load_project_dotenv(override=True)
    clear_settings_cache()
    return get_settings()


__all__ = ["Settings", "get_settings", "initialize_settings"]
