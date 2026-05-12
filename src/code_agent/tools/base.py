from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from code_agent.schemas import ToolResult


class BaseTool(ABC):
    name: str
    description: str
    parameters_schema: dict[str, Any]

    @abstractmethod
    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        raise NotImplementedError
