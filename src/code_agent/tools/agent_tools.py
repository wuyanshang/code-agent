from __future__ import annotations

import asyncio
import logging
import sys
import threading
from typing import Any

from code_agent.agents.loader import AgentDef, AgentLoader
from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool
from code_agent.utils.json_utils import json_dumps

logger = logging.getLogger(__name__)

# 用于子 agent 进度输出的线程锁（避免多 subagent 并发时输出交叉）
_print_lock = threading.Lock()


def _sub_print(msg: str) -> None:
    with _print_lock:
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()


class ListAgentsTool(BaseTool):
    name = "list_agents"
    description = "列出可用的子 agent 及其描述。"
    parameters_schema = {"type": "object", "properties": {}}

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        loader: AgentLoader | None = getattr(context, "agent_loader", None)
        if loader is None:
            return ToolResult(ok=False, content="", error="agent_loader not configured")
        agents = loader.list_agents()
        if not agents:
            return ToolResult(ok=True, content="暂无可用 agent。")
        lines = [f"• {a.name} — {a.description}" for a in agents]
        return ToolResult(ok=True, content="\n".join(lines))


class DelegateAgentTool(BaseTool):
    name = "delegate_agent"
    description = (
        "将一个子任务委派给专门的 agent（等同于 Task 工具）。"
        "该 agent 使用独立的系统提示和工具集来完成任务，然后将结果返回给你。\n"
        "参数说明：\n"
        "  agent/subagent_type: agent 名称\n"
        "  task/prompt:         任务描述\n"
        "  description:         任务简短标题（用于进度显示，可选）\n"
        "  subcommand_approval: 子 agent 执行需审批命令时的策略：'auto'(自动通过) 或 'deny'(自动拒绝)，默认 'auto'"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "agent":              {"type": "string", "description": "子 agent 名称"},
            "subagent_type":      {"type": "string", "description": "子 agent 名称（agent 的别名，与 Task 工具兼容）"},
            "task":               {"type": "string", "description": "委派给子 agent 的任务"},
            "prompt":             {"type": "string", "description": "委派给子 agent 的任务（task 的别名，与 Task 工具兼容）"},
            "description":        {"type": "string", "description": "任务简短标题，用于进度显示"},
            "subcommand_approval": {
                "type": "string",
                "enum": ["auto", "deny"],
                "description": "子 agent 执行需审批命令时：auto=自动通过，deny=自动拒绝。默认 auto。",
            },
        },
        "required": [],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        loader: AgentLoader | None = getattr(context, "agent_loader", None)
        if loader is None:
            return ToolResult(ok=False, content="", error="agent_loader not configured")

        # 兼容 claude-code Task 工具的参数名
        agent_name = arguments.get("agent") or arguments.get("subagent_type", "")
        task = arguments.get("task") or arguments.get("prompt", "")
        if not agent_name or not task:
            return ToolResult(ok=False, content="", error="需要提供 agent（或 subagent_type）和 task（或 prompt）参数")

        description = arguments.get("description", "")
        subcommand_approval = arguments.get("subcommand_approval", "auto")

        agent_def = loader.get_agent(agent_name)
        if agent_def is None:
            available = [a.name for a in loader.list_agents()]
            return ToolResult(
                ok=False, content="",
                error=f"agent '{agent_name}' not found. available: {', '.join(available) or 'none'}",
            )

        label = description or task[:60]
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(
                    asyncio.run,
                    self._run_sub_agent(agent_def, task, context, label, subcommand_approval),
                ).result()
            return result

        return asyncio.run(
            self._run_sub_agent(agent_def, task, context, label, subcommand_approval)
        )

    async def _run_sub_agent(
        self,
        agent_def: AgentDef,
        task: str,
        parent_context: Any,
        label: str = "",
        subcommand_approval: str = "auto",
    ) -> ToolResult:
        from code_agent.agent.context import AgentContext
        from code_agent.llm import create_llm_client, ModelConfig
        from code_agent.safety.command_guard import CommandGuard
        from code_agent.safety.path_guard import PathGuard
        from code_agent.skills.loader import SkillLoader
        from code_agent.tools.registry import ToolRegistry

        parent_config = parent_context.config
        if agent_def.model:
            model_cfg = ModelConfig(
                provider=parent_config.model.provider,
                model_name=agent_def.model,
                base_url=parent_config.model.base_url,
                api_key=parent_config.model.api_key,
                timeout_seconds=parent_config.model.timeout_seconds,
            )
        else:
            model_cfg = parent_config.model

        llm = create_llm_client(model_cfg)

        parent_registry: ToolRegistry = (
            parent_context._tool_registry
            if hasattr(parent_context, "_tool_registry")
            else None
        )
        if parent_registry is None:
            from code_agent.app import build_tool_registry
            parent_registry = build_tool_registry()

        if agent_def.tools:
            allowed = set(agent_def.tools)
        else:
            allowed = set(parent_registry._tools.keys())
        if agent_def.disallowed_tools:
            allowed -= set(agent_def.disallowed_tools)

        schemas = [
            s for s in parent_registry.tool_schemas()
            if s["function"]["name"] in allowed
        ]

        # ── 命令审批策略 ──────────────────────────────────────────────
        # subcommand_approval='auto'  → 需审批的命令自动通过（CommandGuard 已拦危险命令）
        # subcommand_approval='deny'  → 需审批的命令自动拒绝（更保守，适合只读 agent）
        auto_approve = subcommand_approval != "deny"

        class _SubAgentApprovalHandler:
            def is_approved(self, command: str, reason: str) -> bool:
                if auto_approve:
                    return True
                _sub_print(f"  [subagent:{agent_def.name}] 命令被策略拒绝(subcommand_approval=deny): {command}")
                return False

        from code_agent.skills import BUNDLED_SKILLS_DIR
        import pathlib
        root = parent_context.project_root
        project_skills = root / parent_config.skills.directory
        personal_skills = pathlib.Path.home() / ".code-agent" / "skills"

        sub_context = AgentContext(
            config=parent_config,
            project_root=root,
            path_guard=PathGuard(root, parent_config.project.ignore_patterns),
            command_guard=CommandGuard(parent_config.command_policy),
            skill_loader=SkillLoader(personal_skills, project_skills, BUNDLED_SKILLS_DIR),
            approval_handler=_SubAgentApprovalHandler(),
            _tool_registry=parent_registry,
        )

        system_prompt = self._build_system_prompt(agent_def)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        max_turns = agent_def.max_turns or 8
        final_text = ""
        _tag = f"subagent:{agent_def.name}"
        if label:
            _sub_print(f"\n  ▶ [{_tag}] {label}")

        try:
            for _turn in range(max_turns):
                response = await llm.chat(messages, schemas)

                if not response.tool_calls:
                    final_text = response.text.strip()
                    break

                # 进度：显示本轮调用的工具列表
                tool_names = [tc.name for tc in response.tool_calls]
                _sub_print(f"  │ [{_tag}] step {_turn + 1} — {', '.join(tool_names)}")

                assistant_tool_calls = []
                for i, tc in enumerate(response.tool_calls, start=1):
                    tc_id = tc.id or f"sub_{_turn}_{i}"
                    assistant_tool_calls.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json_dumps(tc.arguments)},
                    })
                messages.append({
                    "role": "assistant",
                    "content": response.text or "",
                    "tool_calls": assistant_tool_calls,
                })

                for i, tc in enumerate(response.tool_calls, start=1):
                    tc_id = tc.id or f"sub_{_turn}_{i}"
                    if tc.name not in allowed:
                        messages.append({
                            "role": "tool", "tool_call_id": tc_id,
                            "content": f"tool '{tc.name}' not available for this agent.",
                        })
                        continue
                    try:
                        result = parent_registry.execute(tc.name, tc.arguments, sub_context)
                        status = "✓" if result.ok else "✗"
                        preview = (result.content or result.error or "")[:80].replace("\n", " ")
                        _sub_print(f"  │   {status} {tc.name}: {preview}")
                    except Exception as exc:
                        _sub_print(f"  │   ✗ {tc.name}: {exc}")
                        messages.append({
                            "role": "tool", "tool_call_id": tc_id,
                            "content": f"Tool failed: {exc}",
                        })
                        continue
                    messages.append({
                        "role": "tool", "tool_call_id": tc_id,
                        "content": result.content if result.ok else (result.error or "failed"),
                    })

                if response.text:
                    final_text = response.text.strip()
            else:
                final_text = final_text or "子 agent 达到最大轮数但未返回最终回答。"

            preview = final_text[:100].replace("\n", " ")
            _sub_print(f"  ✓ [{_tag}] 完成 — {preview}")
        except Exception as exc:
            _sub_print(f"  ✗ [{_tag}] 异常: {exc}")
            raise
        finally:
            await llm.close()

        return ToolResult(ok=True, content=final_text)

    @staticmethod
    def _build_system_prompt(agent_def: AgentDef) -> str:
        parts = [f"你是一个专门的子 agent：{agent_def.name}"]
        if agent_def.description:
            parts.append(f"\n{agent_def.description}")
        if agent_def.system_prompt:
            parts.append(f"\n\n{agent_def.system_prompt}")
        parts.append(
            "\n\n请专注于完成委派给你的任务，完成后直接返回分析结果，不要多余的寒暄。"
        )
        return "".join(parts)


class TaskTool(DelegateAgentTool):
    """Task 工具 —— DelegateAgentTool 的别名，与 claude-code Task 工具保持同名。
    LLM 习惯调用 Task({description, prompt, subagent_type}) 时可以直接映射。
    """

    name = "Task"
    description = (
        "将子任务委派给专门的 agent 并等待结果（等同于 delegate_agent）。\n"
        "参数：description（短标题）、prompt（任务内容）、subagent_type（agent 名称）、"
        "subcommand_approval（子 agent 命令策略：auto/deny，默认 auto）"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "description":         {"type": "string", "description": "任务简短标题（3-5 词），用于进度显示"},
            "prompt":              {"type": "string", "description": "委派给子 agent 的完整任务描述"},
            "subagent_type":       {"type": "string", "description": "子 agent 名称"},
            "subcommand_approval": {
                "type": "string",
                "enum": ["auto", "deny"],
                "description": "子 agent 执行需审批命令时：auto=自动通过，deny=自动拒绝，默认 auto",
            },
        },
        "required": ["prompt"],
    }
