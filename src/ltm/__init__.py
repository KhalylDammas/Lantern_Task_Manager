"""Lantern Task Manager (LTM) domain and integrations."""

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    try:
        return version("lantern-task-manager")
    except PackageNotFoundError:
        return "0.1.0"
