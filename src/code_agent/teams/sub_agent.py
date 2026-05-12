from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_agent.agent.context import AgentContext
from code_agent.agent.prompt_builder import PromptBuilder
from code_agent.agent.runner import ApprovalHandler
from code_agent.config import AppConfig
from code_agent.llm.base import BaseLLMClient
from code_agent.safety.command_guard import CommandGuard
from code_agent.safety.path_guard import PathGuard
from code_agent.schemas import ExecutionResult
from code_agent.skills.loader import SkillLoader
from code_agent.teams.config import AgentRoleConfig
from code_agent.tools.registry import ToolRegistry
from code_agent.utils.json_utils import json_dumps

logger = logging.getLogger(__name__)


@dataclass
class SubAgentResult:
    role: str
    task: str
    result: ExecutionResult
    error: str | None = None


class SubAgent:
    """A lightweight agent that runs with a specific role and restricted tool set."""

    def __init__(
        self,
        role_config: AgentRoleConfig,
        app_config: AppConfig,
        llm_client: BaseLLMClient,
        full_registry: ToolRegistry,
        max_context_messages: int = 40,
        trim_keep_recent: int = 20,
    ) -> None:
        self.role_config = role_config
        self.app_config = app_config
        self.llm_client = llm_client
        self.registry = self._build_filtered_registry(full_registry)
        self.max_context_messages = max_context_messages
        self.trim_keep_recent = trim_keep_recent

    def _build_filtered_registry(self, full_registry: ToolRegistry) -> ToolRegistry:
        if not self.role_config.tools:
            return full_registry
        filtered = ToolRegistry()
        for name in self.role_config.tools:
            try:
                filtered.register(full_registry.get(name))
            except KeyError:
                logger.warning("role %s references unknown tool: %s", self.role_config.name, name)
        return filtered

    async def run(self, task: str, project_root: Path) -> SubAgentResult:
        try:
            result = await self._execute(task, project_root)
            return SubAgentResult(role=self.role_config.name, task=task, result=result)
        except Exception as exc:
            logger.error("sub-agent %s failed: %s", self.role_config.name, exc)
            return SubAgentResult(
                role=self.role_config.name,
                task=task,
                result=ExecutionResult(
                    final_answer=f"子 Agent [{self.role_config.name}] 执行异常: {exc}",
                    stopped_reason="error",
                ),
                error=str(exc),
            )

    async def _execute(self, task: str, project_root: Path) -> ExecutionResult:
        from code_agent.skills import BUNDLED_SKILLS_DIR
        root = project_root.resolve()
        project_skills = Path(self.app_config.skills.directory)
        if not project_skills.is_absolute():
            project_skills = (root / project_skills).resolve()
        personal_skills = Path.home() / ".code-agent" / "skills"

        context = AgentContext(
            config=self.app_config,
            project_root=root,
            path_guard=PathGuard(root, self.app_config.project.ignore_patterns),
            command_guard=CommandGuard(self.app_config.command_policy),
            skill_loader=SkillLoader(personal_skills, project_skills, BUNDLED_SKILLS_DIR),
            approval_handler=ApprovalHandler(interactive=False),
        )

        system_prompt = self._build_system_prompt(context)
        context.messages.append({"role": "system", "content": system_prompt})
        context.messages.append({"role": "user", "content": task})

        tool_failures = 0
        tool_history: list[dict[str, Any]] = []

        for step in range(self.app_config.agent.max_steps):
            logger.info("sub-agent [%s] step %s", self.role_config.name, step + 1)

            self._trim_context(context.messages)

            response = await self.llm_client.chat(
                context.messages, self.registry.tool_schemas()
            )

            if response.tool_calls:
                assistant_tool_calls = []
                for index, call in enumerate(response.tool_calls, start=1):
                    tool_call_id = call.id or f"sub_{self.role_config.name}_{step + 1}_{index}"
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
                    {"role": "assistant", "content": response.text or "", "tool_calls": assistant_tool_calls}
                )

                for index, call in enumerate(response.tool_calls, start=1):
                    tool_call_id = call.id or f"sub_{self.role_config.name}_{step + 1}_{index}"
                    try:
                        result = self.registry.execute(call.name, call.arguments, context)
                    except Exception as exc:
                        tool_failures += 1
                        tool_history.append({"tool": call.name, "ok": False, "error": str(exc)})
                        context.messages.append(
                            {"role": "tool", "tool_call_id": tool_call_id, "content": f"Tool failed: {exc}"}
                        )
                        continue

                    tool_history.append({"tool": call.name, "ok": result.ok, "error": result.error})
                    if not result.ok:
                        tool_failures += 1
                    context.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result.content if result.ok else (result.error or "tool failed"),
                        }
                    )

                if tool_failures >= self.app_config.agent.max_tool_failures:
                    return ExecutionResult(
                        final_answer=f"子 Agent [{self.role_config.name}] 工具失败过多，已停止。",
                        tool_calls=tool_history,
                        files_changed=sorted(context.files_changed),
                        commands_run=context.commands_run,
                        stopped_reason="too_many_tool_failures",
                    )
                continue

            return ExecutionResult(
                final_answer=response.text.strip(),
                tool_calls=tool_history,
                files_changed=sorted(context.files_changed),
                diff_preview=context.last_diff,
                commands_run=context.commands_run,
                stopped_reason="completed",
            )

        return ExecutionResult(
            final_answer=f"子 Agent [{self.role_config.name}] 达到最大步数。",
            tool_calls=tool_history,
            files_changed=sorted(context.files_changed),
            commands_run=context.commands_run,
            stopped_reason="max_steps_reached",
        )

    def _build_system_prompt(self, context: AgentContext) -> str:
        base = context.config.agent.system_prompt.strip()
        role_desc = f"\n\n你的角色是: {self.role_config.name}\n{self.role_config.role}"
        extra = f"\n{self.role_config.system_prompt_extra}" if self.role_config.system_prompt_extra else ""
        suffix = "\n\n如果需要读取项目内容或修改文件，必须通过工具完成。"
        return base + role_desc + extra + suffix

    def _trim_context(self, messages: list[dict[str, Any]]) -> None:
        """裁剪上下文消息，使用实例配置的参数"""
        if len(messages) <= self.max_context_messages:
            return
        preserved = list(messages[:2])
        recent = messages[-self.trim_keep_recent:]
        messages.clear()
        messages.extend(preserved + recent)
