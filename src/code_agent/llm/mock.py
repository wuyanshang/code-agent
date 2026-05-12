from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from code_agent.llm.base import BaseLLMClient, StreamChunk
from code_agent.schemas import LLMResponse, ToolCall


class MockLLMClient(BaseLLMClient):
    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        if not tools and messages:
            blob = json.dumps(messages, ensure_ascii=False)
            if "请将以下对话压缩" in blob or "对话压缩助手" in blob:
                return LLMResponse(
                    text=(
                        "[Mock 摘要]\n"
                        "- 用户与助手曾讨论代码、工具与文件。\n"
                        "- 未决事项：按后续用户指令继续。"
                    )
                )

        tool_messages = [msg for msg in messages if msg.get("role") == "tool"]
        if tool_messages:
            last_tool = tool_messages[-1]
            return LLMResponse(
                text=f"Mock 模式已完成一次工具调用。\n工具输出如下：\n{last_tool.get('content', '').strip()}".strip()
            )

        user_message = next((msg.get("content", "") for msg in reversed(messages) if msg.get("role") == "user"), "")
        prompt = user_message.lower()

        if "python" in prompt:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="run_command",
                        arguments={
                            "command": "python demo.py",
                            "reason": "mock mode requested a python command for approval testing",
                        },
                    )
                ]
            )

        if "列出" in user_message or "list" in prompt or "项目结构" in user_message:
            return LLMResponse(tool_calls=[ToolCall(name="list_files", arguments={"path": ".", "max_depth": 2})])

        if "readme" in prompt:
            return LLMResponse(tool_calls=[ToolCall(name="read_file", arguments={"path": "README.md"})])

        if "搜索" in user_message or "search" in prompt:
            return LLMResponse(tool_calls=[ToolCall(name="search_text", arguments={"query": "code-agent"})])

        return LLMResponse(
            text="Mock 模式当前支持几类演示任务：列目录、读取 README、搜索关键词、触发 python 命令审批。"
        )

    async def chat_stream(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncGenerator[StreamChunk, None]:
        response = await self.chat(messages, tools)
        if response.text:
            for char in response.text:
                yield StreamChunk(type="text_delta", text=char)
                await asyncio.sleep(0.01)
        for i, tc in enumerate(response.tool_calls):
            yield StreamChunk(
                type="tool_call",
                tool_index=i,
                tool_call_id=tc.id or f"mock_{i}",
                tool_name=tc.name,
                tool_arguments_delta="{}" if not tc.arguments else __import__("json").dumps(tc.arguments, ensure_ascii=False),
            )
        yield StreamChunk(type="done", finish_reason="stop" if response.text else "tool_calls")
