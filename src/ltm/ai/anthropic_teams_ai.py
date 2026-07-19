"""Anthropic Claude implementation of Teams `AIModel` (C09 primary)."""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, cast

from anthropic import AsyncAnthropic

from microsoft_teams.ai import (
    AIModel,
    Function,
    FunctionCall,
    FunctionMessage,
    ListMemory,
    Memory,
    Message,
    ModelMessage,
    SystemMessage,
    UserMessage,
)
from microsoft_teams.ai.function import FunctionHandler, FunctionHandlerWithNoParams
from microsoft_teams.openai.function_utils import get_function_schema, parse_function_arguments
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _to_anthropic_tools(functions: dict[str, Function[BaseModel]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, fn in functions.items():
        schema = get_function_schema(fn) or {"type": "object", "properties": {}}
        schema = {**schema, "type": schema.get("type", "object")}
        out.append({"name": name, "description": fn.description or name, "input_schema": schema})
    return out


def _messages_for_api(history: list[Message], pending: Message | None) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []

    def append_from_message(m: Message) -> None:
        if isinstance(m, UserMessage):
            msgs.append({"role": "user", "content": m.content})
        elif isinstance(m, ModelMessage):
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            if m.function_calls:
                for fc in m.function_calls:
                    blocks.append(
                        {"type": "tool_use", "id": fc.id, "name": fc.name, "input": fc.arguments or {}}
                    )
            if blocks:
                msgs.append({"role": "assistant", "content": blocks})
        elif isinstance(m, FunctionMessage):
            msgs.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": m.function_id, "content": m.content or ""}
                    ],
                }
            )

    for m in history:
        append_from_message(m)
    if pending is not None:
        append_from_message(pending)
    return msgs


@dataclass
class AnthropicTeamsAIModel(AIModel):
    """Claude Messages API with native tool_use / tool_result loop."""

    api_key: str
    model: str

    async def generate_text(
        self,
        input: Message,
        *,
        system: SystemMessage | None = None,
        memory: Memory | None = None,
        functions: dict[str, Function[BaseModel]] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ModelMessage:
        if on_chunk:
            logger.warning("Streaming not implemented for Anthropic adapter; ignoring on_chunk.")

        if memory is None:
            memory = ListMemory()

        function_results = await self._execute_functions(input, functions)

        hist = list(await memory.get_all())
        await memory.push(input)

        if function_results:
            hist.append(input)
            for res in function_results:
                await memory.push(res)
                hist.append(res)
            pending: Message | None = None
        else:
            pending = input

        sys_txt = system.content if isinstance(system, SystemMessage) else ""
        client = AsyncAnthropic(api_key=self.api_key)

        tool_defs = _to_anthropic_tools(functions or {})

        api_msgs = _messages_for_api(hist, pending)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "system": sys_txt or "",
            "messages": api_msgs,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs

        resp = await client.messages.create(**kwargs)

        tool_blocks = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if tool_blocks:
            calls: list[FunctionCall] = []
            for b in tool_blocks:
                raw_in = getattr(b, "input", {}) or {}
                if hasattr(raw_in, "model_dump"):
                    args = raw_in.model_dump()
                elif isinstance(raw_in, dict):
                    args = raw_in
                else:
                    args = {}
                calls.append(FunctionCall(id=b.id, name=b.name, arguments=args))
            model_response = ModelMessage(content=None, function_calls=calls)
            return await self.generate_text(model_response, system=system, memory=memory, functions=functions)

        texts = [getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"]
        final = "\n".join(t for t in texts if t).strip() or None
        model_final = ModelMessage(content=final, function_calls=None)
        await memory.push(model_final)
        return model_final

    async def _execute_functions(
        self, input: Message, functions: dict[str, Function[BaseModel]] | None
    ) -> list[FunctionMessage]:
        results: list[FunctionMessage] = []
        if isinstance(input, ModelMessage) and input.function_calls:
            for call in input.function_calls:
                if not functions or call.name not in functions:
                    continue
                fn = functions[call.name]
                try:
                    parsed = parse_function_arguments(fn, call.arguments)
                    handler = cast(FunctionHandler[BaseModel], fn.handler)
                    ret = handler(parsed) if parsed else cast(FunctionHandlerWithNoParams, fn.handler)()
                    out = await ret if inspect.isawaitable(ret) else str(ret)
                    results.append(FunctionMessage(content=out, function_id=call.id))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Anthropic tool %s failed", call.name)
                    results.append(FunctionMessage(content=f"Function execution failed: {exc}", function_id=call.id))
        return results
