"""Optional in-channel notification hook (Phase 4 placeholder).

When task creation occurs in a team/group chat, future work can @mention the assignee
in-thread using the originating ConversationReference instead of 1:1 delivery.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify_assignee_in_thread_if_applicable(**kwargs) -> bool:
    """Not implemented — group/channel scoped notifications deferred."""
    logger.debug("In-thread assignee notification not implemented: %s", list(kwargs.keys()))
    return False
