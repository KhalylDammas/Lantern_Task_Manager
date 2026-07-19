"""Load task_catalogue, manager_map, escalation_rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ltm.config.settings import config_dir


def _load_json(name: str) -> dict[str, Any]:
    path = Path(config_dir()) / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_task_catalogue() -> dict[str, Any]:
    return _load_json("task_catalogue.json")


def load_manager_map() -> dict[str, Any]:
    return _load_json("manager_map.json")


def load_escalation_rules() -> dict[str, Any]:
    return _load_json("escalation_rules.json")


def load_assignment_directory() -> dict[str, Any]:
    return _load_json("assignment_directory.json")


def load_assignment_policy() -> dict[str, Any]:
    return _load_json("assignment_policy.json")
