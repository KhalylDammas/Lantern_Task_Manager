"""Bounded conversation memory for LLM context (DM-03, Groq TPM mitigation)."""

from __future__ import annotations

import logging

from microsoft_teams.ai import FunctionMessage, ListMemory, Message, UserMessage

logger = logging.getLogger(__name__)


def _split_into_turns(messages: list[Message]) -> list[list[Message]]:
    """Group messages into user-initiated turns (UserMessage starts a new turn)."""
    turns: list[list[Message]] = []
    current: list[Message] = []
    for message in messages:
        if isinstance(message, UserMessage) and current:
            turns.append(current)
            current = [message]
        else:
            current.append(message)
    if current:
        turns.append(current)
    return turns


def _truncate_tool_result(message: Message, *, max_chars: int) -> Message:
    if max_chars <= 0 or not isinstance(message, FunctionMessage):
        return message
    content = message.content
    if not isinstance(content, str) or len(content) <= max_chars:
        return message
    omitted = len(content) - max_chars
    return FunctionMessage(
        content=f"{content[:max_chars]}\n...[truncated {omitted} chars]",
        function_id=message.function_id,
    )


def trim_messages(
    messages: list[Message],
    *,
    max_turns: int,
    max_tool_result_chars: int = 0,
) -> list[Message]:
    """Keep the most recent user turns and optionally cap tool-result size."""
    if max_turns <= 0:
        return list(messages)

    turns = _split_into_turns(messages)
    kept_turns = turns[-max_turns:] if len(turns) > max_turns else turns
    trimmed: list[Message] = []
    for turn in kept_turns:
        for message in turn:
            trimmed.append(_truncate_tool_result(message, max_chars=max_tool_result_chars))
    return trimmed


async def trim_conversation_memory(
    memory: ListMemory,
    *,
    max_turns: int,
    max_tool_result_chars: int = 0,
) -> int:
    """Trim in-place conversation memory; returns number of messages removed."""
    messages = list(await memory.get_all())
    if not messages:
        return 0

    trimmed = trim_messages(
        messages,
        max_turns=max_turns,
        max_tool_result_chars=max_tool_result_chars,
    )
    removed = len(messages) - len(trimmed)
    if removed <= 0 and trimmed == messages:
        return 0

    await memory.set_all(trimmed)
    if removed > 0:
        logger.info(
            "Trimmed conversation memory: kept_turns<=%s removed_messages=%s remaining_messages=%s",
            max_turns,
            removed,
            len(trimmed),
        )
    return removed
