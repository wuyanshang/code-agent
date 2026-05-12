import asyncio
from pathlib import Path

from code_agent.agent.runner import AgentRunner
from code_agent.config import AppConfig
from code_agent.schemas import LLMResponse, ToolCall
from code_agent.tools.shell_tools import RunCommandTool
from code_agent.tools.registry import ToolRegistry


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(name="run_command", arguments={"command": "pip install flask", "reason": "install dependency"})])
        return LLMResponse(text="done")


def test_runner_returns_pending_approval(tmp_path: Path) -> None:
    config = AppConfig()
    config.skills.directory = str((tmp_path / "skills").resolve())
    (tmp_path / "skills").mkdir()
    registry = ToolRegistry()
    registry.register(RunCommandTool())
    runner = AgentRunner(config=config, llm_client=FakeLLM(), tool_registry=registry, interactive=False)
    result = asyncio.run(runner.run("check", project_root=tmp_path))
    assert result.stopped_reason == "pending_approval"
    assert result.pending_approval is not None
    assert result.pending_approval.command == "pip install flask"
