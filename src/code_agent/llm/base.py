from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from code_agent.schemas import LLMResponse


@dataclass
class StreamChunk:
    type: str
    text: str = ""
    tool_index: int = 0
    tool_call_id: str = ""
    tool_name: str = ""
    tool_arguments_delta: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class BaseLLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        raise NotImplementedError

    async def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncGenerator[StreamChunk, None]:
        response = await self.chat(messages, tools)
        if response.text:
            yield StreamChunk(type="text_delta", text=response.text)
        for i, tc in enumerate(response.tool_calls):
            yield StreamChunk(
                type="tool_call_delta",
                tool_index=i,
                tool_call_id=tc.id or "",
                tool_name=tc.name,
                tool_arguments_delta="",
            )
        yield StreamChunk(type="done", finish_reason=response.finish_reason)

    async def close(self) -> None:
        pass
