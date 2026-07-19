"""Groq OpenAI-compatible chat: message-shape and API quirks vs stock OpenAICompletionsAIModel."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ltm.ai.groq_metrics import begin_call, get_call_metrics

from microsoft_teams.ai import (
    Function,
    FunctionMessage,
    Memory,
    Message,
    ModelMessage,
    SystemMessage,
    UserMessage,
)
from microsoft_teams.openai.completions_model import OpenAICompletionsAIModel
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from pydantic import BaseModel


class GroqOpenAICompletionsAIModel(OpenAICompletionsAIModel):
    """Groq: omit null tool_calls on assistant turns; disable streaming when tools are enabled; parallel_tool_calls default false."""

    def __post_init__(self) -> None:
        super().__post_init__()
        client = self._client
        orig_create = client.chat.completions.create

        async def _groq_create(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("parallel_tool_calls", False)
            begin_call()
            started = time.perf_counter()
            response = await orig_create(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            metrics = get_call_metrics()
            if metrics is not None:
                metrics.latency_ms = elapsed_ms
                usage = getattr(response, "usage", None)
                if usage is not None:
                    metrics.prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                    metrics.completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            return response

        client.chat.completions.create = _groq_create  # type: ignore[method-assign]

    async def generate_text(
        self,
        input: Message,
        *,
        system: SystemMessage | None = None,
        memory: Memory | None = None,
        functions: dict[str, Function[BaseModel]] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ModelMessage:
        if functions and on_chunk is not None:
            on_chunk = None
        return await super().generate_text(
            input, system=system, memory=memory, functions=functions, on_chunk=on_chunk
        )

    def _convert_message_to_openai_format(self, message: Message) -> ChatCompletionMessageParam:
        if isinstance(message, UserMessage):
            return ChatCompletionUserMessageParam(role=message.role, content=message.content)
        if isinstance(message, SystemMessage):
            return ChatCompletionSystemMessageParam(role=message.role, content=message.content)
        if isinstance(message, FunctionMessage):
            return ChatCompletionToolMessageParam(
                role="tool",
                content=message.content or [],
                tool_call_id=message.function_id,
            )
        if isinstance(message, ModelMessage):
            if message.function_calls:
                tool_calls = [
                    ChatCompletionMessageFunctionToolCallParam(
                        id=call.id,
                        function={"name": call.name, "arguments": json.dumps(call.arguments)},
                        type="function",
                    )
                    for call in message.function_calls
                ]
                return ChatCompletionAssistantMessageParam(
                    role="assistant", content=message.content, tool_calls=tool_calls
                )
            return ChatCompletionAssistantMessageParam(role="assistant", content=message.content)
        raise Exception(f"Message {message} not supported")
