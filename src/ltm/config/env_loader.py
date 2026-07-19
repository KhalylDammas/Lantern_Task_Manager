"""Single source of truth for dotenv file discovery (local + Toolkit dev)."""

from __future__ import annotations

from pathlib import Path
import os

from dotenv import dotenv_values, load_dotenv


# Teams Toolkit stores deploy-time secrets under SECRET_* names.  Local app
# startup and Alembic use the runtime names that Bicep installs in App Service.
# Mirroring them here makes ``TEAMSFX_ENV=prod`` behave like the deployed app.
_TOOLKIT_RUNTIME_ALIASES = {
    "BOT_ID": "CLIENT_ID",
    "SECRET_BOT_PASSWORD": "CLIENT_SECRET",
    "TEAMS_APP_TENANT_ID": "TENANT_ID",
    "SECRET_OPENAI_API_KEY": "OPENAI_API_KEY",
    "SECRET_GROQ_API_KEY": "GROQ_API_KEY",
    "SECRET_TURSO_DATABASE_URL": "TURSO_DATABASE_URL",
    "SECRET_TURSO_AUTH_TOKEN": "TURSO_AUTH_TOKEN",
    "SECRET_D365_CLIENT_SECRET": "D365_CLIENT_SECRET",
    "SECRET_LTM_CRON_SECRET": "LTM_CRON_SECRET",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def dotenv_paths() -> tuple[Path, ...]:
    root = repo_root()
    generated = root / ".env"
    generated_values = dotenv_values(generated) if generated.is_file() else {}
    requested_env = (os.environ.get("TEAMSFX_ENV") or "").strip().lower()
    generated_env = str(generated_values.get("TEAMSFX_ENV") or "").strip().lower()
    active_env = (
        requested_env
        or generated_env
        or "local"
    )
    if not active_env.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid TEAMSFX_ENV: {active_env!r}")

    # A Toolkit-generated root .env is environment-specific despite its generic
    # filename. Never mix (for example) its local DATABASE_URL/BOT_SKIP_AUTH into
    # an explicitly selected production environment.
    candidates = []
    if generated.is_file() and (not requested_env or generated_env == active_env):
        candidates.append(generated)
    if active_env:
        candidates.extend(
            [
                root / "env" / f".env.{active_env}",
                root / "env" / f".env.{active_env}.user",
            ]
        )
    return tuple(path for path in candidates if path.is_file())


def load_project_dotenv(*, override: bool = True) -> tuple[Path, ...]:
    """Load all project env files in precedence order (later files win)."""
    loaded: list[Path] = []
    for path in dotenv_paths():
        load_dotenv(path, override=override)
        loaded.append(path)
    for toolkit_name, runtime_name in _TOOLKIT_RUNTIME_ALIASES.items():
        if not os.environ.get(runtime_name) and os.environ.get(toolkit_name):
            os.environ[runtime_name] = os.environ[toolkit_name]
    return tuple(loaded)
