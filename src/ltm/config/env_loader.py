"""Single source of truth for dotenv file discovery (local + Toolkit dev)."""

from __future__ import annotations

from pathlib import Path
import os

from dotenv import dotenv_values, load_dotenv


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def dotenv_paths() -> tuple[Path, ...]:
    root = repo_root()
    generated = root / ".env"
    generated_values = dotenv_values(generated) if generated.is_file() else {}
    active_env = (
        os.environ.get("TEAMSFX_ENV")
        or generated_values.get("TEAMSFX_ENV")
        or "local"
    ).strip().lower()
    if not active_env.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid TEAMSFX_ENV: {active_env!r}")

    candidates = [generated]
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
    return tuple(loaded)
