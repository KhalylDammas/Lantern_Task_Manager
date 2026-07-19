from __future__ import annotations

from ltm.config import env_loader


def test_dotenv_paths_are_isolated_to_active_environment(monkeypatch) -> None:
    monkeypatch.setenv("TEAMSFX_ENV", "playground")
    paths = env_loader.dotenv_paths()
    names = {path.name for path in paths}

    assert ".env" in names
    assert ".env.playground" in names
    assert ".env.playground.user" in names
    assert ".env.dev" not in names
    assert ".env.local" not in names


def test_dotenv_paths_reject_unsafe_environment_name(monkeypatch) -> None:
    monkeypatch.setenv("TEAMSFX_ENV", "../dev")
    try:
        env_loader.dotenv_paths()
    except ValueError as exc:
        assert "Invalid TEAMSFX_ENV" in str(exc)
    else:
        raise AssertionError("unsafe environment name was accepted")
