import asyncio
import json
from pathlib import Path

from code_agent.config import AppConfig
from code_agent.schemas import LLMResponse
from code_agent.teams.config import AgentRoleConfig, TeamConfig
from code_agent.teams.orchestrator import TeamOrchestrator, _parse_plan
from code_agent.tools.file_tools import ListFilesTool, ReadFileTool
from code_agent.tools.registry import ToolRegistry


class FakeTeamLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                text=json.dumps(
                    {
                        "framing": "Check project structure and code quality risks.",
                        "hypotheses": ["The repository structure is understandable."],
                        "tasks": [
                            {"role": "scout", "task": "List project files"},
                            {"role": "critic", "task": "Review code quality risks"},
                        ],
                        "open_questions": ["Are there obvious structural issues?"],
                        "should_implement": False,
                    }
                )
            )
        if tools:
            return LLMResponse(text="Sub-task completed.")
        if self.calls == 4:
            return LLMResponse(
                text=json.dumps(
                    {
                        "assessment": "Enough evidence for a first-pass decision.",
                        "gaps": [],
                        "follow_up_tasks": [],
                        "ready_for_decision": True,
                    }
                )
            )
        return LLMResponse(
            text=json.dumps(
                {
                    "summary": "Project structure looks reasonable and no major code-quality issue was found in this pass.",
                    "decision": "continue",
                    "confidence": "medium",
                    "recommended_next_step": "Move to targeted implementation only after a concrete change request.",
                    "open_questions": [],
                    "evidence": [
                        "scout found a coherent structure",
                        "critic did not find a major issue",
                    ],
                }
            )
        )


def test_parse_plan_valid_json() -> None:
    plan = _parse_plan(
        '[{"role": "coder", "task": "write code"}, {"role": "reviewer", "task": "review"}]',
        ["coder", "reviewer"],
    )
    assert len(plan) == 2
    assert plan[0]["role"] == "coder"
    assert plan[1]["task"] == "review"


def test_parse_plan_markdown_wrapped() -> None:
    plan = _parse_plan(
        '```json\n[{"role": "coder", "task": "write code"}]\n```',
        ["coder"],
    )
    assert len(plan) == 1
    assert plan[0]["role"] == "coder"


def test_parse_plan_fallback() -> None:
    plan = _parse_plan("this is not JSON", ["assistant"])
    assert len(plan) == 1
    assert plan[0]["role"] == "assistant"


def test_team_orchestrator_runs(tmp_path: Path) -> None:
    config = AppConfig()
    config.skills.directory = str((tmp_path / "skills").resolve())
    (tmp_path / "skills").mkdir()
    (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")

    team_config = TeamConfig(
        roles=[
            AgentRoleConfig(name="scout", role="Explore codebase"),
            AgentRoleConfig(name="critic", role="Challenge assumptions"),
        ]
    )
    registry = ToolRegistry()
    registry.register(ListFilesTool())
    registry.register(ReadFileTool())

    orchestrator = TeamOrchestrator(
        team_config=team_config,
        app_config=config,
        llm_client=FakeTeamLLM(),
        tool_registry=registry,
    )
    result = asyncio.run(orchestrator.run("inspect project", project_root=tmp_path))
    assert result.task == "inspect project"
    assert len(result.sub_results) == 2
    assert result.summary
    assert result.confidence == "medium"
    assert result.evidence
    assert result.completed is True
    assert result.stopped_reason == "completed"
    assert result.total_tokens_used >= 0
    assert result.llm_calls_count > 0
