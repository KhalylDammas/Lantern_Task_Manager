"""Resolve notification recipients from tasks."""

from __future__ import annotations

import logging

from ltm.config.settings import Settings
from ltm.domain.models import TaskRecord, UserRef

logger = logging.getLogger(__name__)


def assignee_ref(task: TaskRecord) -> UserRef:
    return task.assigned_to


def creator_ref(task: TaskRecord) -> UserRef:
    return task.created_by


def verifier_ref(task: TaskRecord, settings: Settings | None = None) -> UserRef:
    """Resolve closure verifier per LTM_VERIFIER_MODE (default: created_by)."""
    from ltm.config.settings import get_settings

    cfg = settings or get_settings()
    mode = (cfg.verifier_mode or "created_by").strip().lower()

    if mode == "manager_map":
        from ltm.graph.client import manager_for_assignee

        mgr_id = manager_for_assignee(task.assigned_to.entra_object_id)
        if mgr_id:
            return UserRef(entra_object_id=mgr_id, display_name="Manager")
        logger.warning("manager_map miss for assignee %s; falling back to creator", task.assigned_to.entra_object_id)

    if mode == "graph_manager":
        try:
            from ltm.auth.tokens import acquire_graph_token, graph_configured

            if graph_configured(cfg):
                import httpx

                oid = task.assigned_to.entra_object_id.strip()
                token = acquire_graph_token(cfg)
                url = f"https://graph.microsoft.com/v1.0/users/{oid}/manager?$select=id,displayName"
                resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    mgr_id = data.get("id")
                    if mgr_id:
                        return UserRef(
                            entra_object_id=str(mgr_id),
                            display_name=str(data.get("displayName") or "Manager"),
                        )
        except Exception:  # noqa: BLE001
            logger.exception("Graph manager lookup failed for %s", task.assigned_to.entra_object_id)

    return task.created_by


def is_verifier(user_entra_id: str, task: TaskRecord, settings: Settings | None = None) -> bool:
    return verifier_ref(task, settings).entra_object_id == user_entra_id
