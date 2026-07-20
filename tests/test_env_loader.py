from __future__ import annotations

from ltm.config import env_loader


def test_dotenv_paths_are_isolated_to_active_environment(monkeypatch, tmp_path) -> None:
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    for name in (".env.playground", ".env.playground.user", ".env.dev", ".env.local"):
        (env_dir / name).write_text(f"SOURCE={name}\n", encoding="utf-8")

    monkeypatch.setattr(env_loader, "repo_root", lambda: tmp_path)
    monkeypatch.setenv("TEAMSFX_ENV", "playground")
    paths = env_loader.dotenv_paths()
    names = {path.name for path in paths}

    assert ".env" not in names
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


def test_toolkit_secrets_are_available_under_runtime_names(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env.prod.user"
    env_file.write_text(
        "BOT_ID=bot-id\n"
        "SECRET_BOT_PASSWORD=bot-secret\n"
        "SECRET_TURSO_DATABASE_URL=libsql://prod.example\n"
        "SECRET_TURSO_AUTH_TOKEN=db-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(env_loader, "dotenv_paths", lambda: (env_file,))
    for name in (
        "BOT_ID",
        "CLIENT_ID",
        "SECRET_BOT_PASSWORD",
        "CLIENT_SECRET",
        "SECRET_TURSO_DATABASE_URL",
        "TURSO_DATABASE_URL",
        "SECRET_TURSO_AUTH_TOKEN",
        "TURSO_AUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    env_loader.load_project_dotenv()

    assert env_loader.os.environ["CLIENT_ID"] == "bot-id"
    assert env_loader.os.environ["CLIENT_SECRET"] == "bot-secret"
    assert env_loader.os.environ["TURSO_DATABASE_URL"] == "libsql://prod.example"
    assert env_loader.os.environ["TURSO_AUTH_TOKEN"] == "db-secret"
