from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from code_agent.schemas import ToolResult


class BaseTool(ABC):
    name: str
    description: str
    parameters_schema: dict[str, Any]

    # 设为 True 的工具在同一 LLM 步骤中被调用多次时会并发执行（asyncio.gather）
    parallel_capable: bool = False

    @abstractmethod
    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        raise NotImplementedError

    async def execute_async(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        """异步版本，默认回退到同步 execute()。
        parallel_capable=True 的子类应重写此方法以实现真正的并发。
        """
        return self.execute(arguments, context)
