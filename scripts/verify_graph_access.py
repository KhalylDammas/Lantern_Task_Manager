#!/usr/bin/env python3
"""Verify app-only Microsoft Graph access using the same auth path as the bot.

Reads environment the same way the app does (App Service settings or local .env files).

Usage (from repo root):
  python scripts/verify_graph_access.py

Exit code 0 when Graph is reachable, 1 otherwise.
See docs/runbooks/graph-azure-msi.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ltm.auth.tokens import verify_graph_access  # noqa: E402
from ltm.config.settings import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    ok, mode, detail = verify_graph_access(settings)
    print(f"CLIENT_ID: {settings.client_id or '(not set)'}")
    print(f"BOT_TYPE:  {settings.bot_type or '(not set)'}")
    print(f"mode:      {mode}")
    print(f"ok:        {ok}")
    print(f"detail:    {detail}")
    if not ok:
        print(
            "\nRemediation:"
            "\n  Azure MSI permissions must be on the App Service CLIENT_ID app (the managed identity),"
            "\n  NOT on the separate local Toolkit bot app from F5/aadApp/create."
            "\n  Run: scripts/grant_msi_graph_permissions.sh "
            f"{settings.client_id or '<msi-client-id>'}"
            "\n  See docs/runbooks/graph-azure-msi.md"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
