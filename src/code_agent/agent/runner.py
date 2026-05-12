from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from code_agent.agent.context import AgentContext
from code_agent.agent.prompt_builder import PromptBuilder
from code_agent.agents.loader import AgentLoader, BUNDLED_AGENTS_DIR
from code_agent.config import AppConfig
from code_agent.llm.base import BaseLLMClient
from code_agent.safety.command_guard import CommandGuard
from code_agent.safety.path_guard import PathGuard
from code_agent.schemas import ExecutionResult
from code_agent.skills.loader import SkillLoader
from code_agent.tools.registry import ToolRegistry
from code_agent.utils.json_utils import json_dumps

logger = logging.getLogger(__name__)

MAX_CONTEXT_MESSAGES = 60
TRIM_KEEP_RECENT = 30


class ApprovalHandler:
    def __init__(self, interactive: bool = True) -> None:
        self.interactive = interactive

    def is_approved(self, command: str, reason: str) -> bool:
        if not self.interactive:
            return False
        print("\n命令需要审批:")
        print(command)
        print(f"原因: {reason}")
        answer = input("是否允许执行? [y/N]: ").strip().lower()
        return answer in {"y", "yes"}


class AgentRunner:
    def __init__(
        self,
        config: AppConfig,
        llm_client: BaseLLMClient,
        tool_registry: ToolRegistry,
        interactive: bool = True,
    ) -> None:
        self.config = config
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.prompt_builder = PromptBuilder()
        self.interactive = interactive

    async def run(
        self,
        task: str,
        project_root: str | Path,
        skill: str | None = None,
    ) -> ExecutionResult:
        from code_agent.skills import BUNDLED_SKILLS_DIR
        root = Path(project_root).resolve()
        project_skills = Path(self.config.skills.directory)
        if not project_skills.is_absolute():
            project_skills = (root / project_skills).resolve()
        personal_skills = Path.home() / ".code-agent" / "skills"
        project_agents = root / ".code-agent" / "agents"
        personal_agents = Path.home() / ".code-agent" / "agents"
        context = AgentContext(
            config=self.config,
            project_root=root,
            path_guard=PathGuard(root, self.config.project.ignore_patterns),
            command_guard=CommandGuard(self.config.command_policy),
            skill_loader=SkillLoader(personal_skills, project_skills, BUNDLED_SKILLS_DIR),
            approval_handler=ApprovalHandler(interactive=self.interactive),
            agent_loader=AgentLoader(personal_agents, project_agents, BUNDLED_AGENTS_DIR),
            _tool_registry=self.tool_registry,
            selected_skill=skill,
        )

        system_prompt = self.prompt_builder.build_system_prompt(context)
        context.messages.append({"role": "system", "content": system_prompt})
        context.messages.append({"role": "user", "content": task})

        tool_failures = 0
        tool_history: list[dict[str, Any]] = []

        for step in range(self.config.agent.max_steps):
            logger.info("agent step %s", step + 1)

            _trim_context(context.messages)

            response = await self.llm_client.chat(
                context.messages, self.tool_registry.tool_schemas()
            )

            if response.tool_calls:
                assistant_tool_calls = []
                for index, call in enumerate(response.tool_calls, start=1):
                    tool_call_id = call.id or f"call_{step + 1}_{index}"
                    assistant_tool_calls.append(
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json_dumps(call.arguments),
                            },
                        }
                    )
                context.messages.append(
                    {
                        "role": "assistant",
                        "content": response.text or "",
                        "tool_calls": assistant_tool_calls,
                    }
                )

                for index, call in enumerate(response.tool_calls, start=1):
                    tool_call_id = call.id or f"call_{step + 1}_{index}"
                    try:
                        result = self.tool_registry.execute(call.name, call.arguments, context)
                    except Exception as exc:
                        tool_failures += 1
                        error_text = str(exc)
                        tool_history.append(
                            {"tool": call.name, "arguments": call.arguments, "ok": False, "error": error_text}
                        )
                        context.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": f"Tool execution failed: {error_text}",
                            }
                        )
                        continue

                    tool_history.append(
                        {
                            "tool": call.name,
                            "arguments": call.arguments,
                            "ok": result.ok,
                            "error": result.error,
                            "metadata": result.metadata,
                        }
                    )
                    if not result.ok:
                        tool_failures += 1
                    context.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result.content if result.ok else (result.error or "tool failed"),
                        }
                    )
                    if "pending_approval" in result.metadata:
                        return ExecutionResult(
                            final_answer="命令需要审批，未执行。",
                            tool_calls=tool_history,
                            files_changed=sorted(context.files_changed),
                            diff_preview=context.last_diff,
                            commands_run=context.commands_run,
                            skill_used=skill,
                            stopped_reason="pending_approval",
                            pending_approval=result.metadata["pending_approval"],
                        )

                if tool_failures >= self.config.agent.max_tool_failures:
                    return ExecutionResult(
                        final_answer="工具调用失败次数过多，执行已停止。",
                        tool_calls=tool_history,
                        files_changed=sorted(context.files_changed),
                        diff_preview=context.last_diff,
                        commands_run=context.commands_run,
                        skill_used=skill,
                        stopped_reason="too_many_tool_failures",
                    )
                continue

            return ExecutionResult(
                final_answer=response.text.strip(),
                tool_calls=tool_history,
                files_changed=sorted(context.files_changed),
                diff_preview=context.last_diff,
                commands_run=context.commands_run,
                skill_used=skill,
                stopped_reason="completed",
            )

        return ExecutionResult(
            final_answer="达到最大步数，执行停止。",
            tool_calls=tool_history,
            files_changed=sorted(context.files_changed),
            diff_preview=context.last_diff,
            commands_run=context.commands_run,
            skill_used=skill,
            stopped_reason="max_steps_reached",
        )


def _trim_context(messages: list[dict[str, Any]]) -> None:
    """Keep system + user + recent messages when context grows too large."""
    if len(messages) <= MAX_CONTEXT_MESSAGES:
        return
    preserved = [m for m in messages[:2]]
    recent = messages[-TRIM_KEEP_RECENT:]
    messages.clear()
    messages.extend(preserved + recent)
