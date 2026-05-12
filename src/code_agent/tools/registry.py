from __future__ import annotations

from typing import Any

from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def execute(self, name: str, arguments: dict[str, Any], context: Any) -> ToolResult:
        return self.get(name).execute(arguments, context)

    def list_names(self) -> list[str]:
        return sorted(self._tools)

    def tool_schemas(self) -> list[dict[str, Any]]:
        schemas = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                }
            )
        return schemas
