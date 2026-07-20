from __future__ import annotations

import ast
from pathlib import Path


def _imports(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_transport_adapters_do_not_depend_on_task_persistence() -> None:
    adapters = ("src/app.py", "src/ltm/bot/tools.py", "src/ltm/bot/card_actions.py")
    forbidden = {"ltm.storage.repository", "ltm.storage.orm"}

    for adapter in adapters:
        assert not (_imports(adapter) & forbidden), f"{adapter} bypasses the application layer"


def test_removed_recovery_placeholders_stay_removed() -> None:
    removed = (
        "src/config.py",
        "src/ltm/bot/session.py",
        "src/ltm/domain/service.py",
        "src/ltm/notifications/channel_thread.py",
    )
    assert all(not Path(path).exists() for path in removed)
