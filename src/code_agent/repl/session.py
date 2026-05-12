from __future__ import annotations

import asyncio
import copy
import json
import logging
from pathlib import Path
from typing import Any, Literal

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory

from code_agent.agent.context import AgentContext
from code_agent.agent.prompt_builder import PromptBuilder
from code_agent.agents.loader import AgentLoader, BUNDLED_AGENTS_DIR
from code_agent.config import AppConfig, apply_model_preset
from code_agent.llm.base import BaseLLMClient, StreamChunk
from code_agent.repl import commands as cmd_mod
from code_agent.repl.renderer import (
    print_approval_prompt,
    print_error,
    print_info,
    print_sub_agent_done,
    print_sub_agent_start,
    print_team_header,
    print_text_chunk,
    print_text_end,
    print_tool_call,
    print_tool_result,
    print_warning,
    print_welcome,
)
from code_agent.safety.command_guard import CommandGuard
from code_agent.safety.path_guard import PathGuard
from code_agent.schemas import CommandDecision, PendingApproval
from code_agent.skills.loader import SkillLoader
from code_agent.tools.registry import ToolRegistry
from code_agent.utils.context_budget import (
    apply_compact,
    estimate_messages_tokens,
    truncate_tool_content,
    truncate_tool_messages_in_history,
)
from code_agent.utils.compact_llm import apply_compact_llm
from code_agent.utils.errors import format_tool_error_for_model
from code_agent.utils.json_utils import json_dumps

logger = logging.getLogger(__name__)

MAX_CONTEXT_MESSAGES = 60
TRIM_KEEP_RECENT = 30


class ReplApprovalHandler:
    def __init__(self, auto_approve: bool = False) -> None:
        self.auto_approve = auto_approve
        self.always_allowed: set[str] = set()

    async def is_approved(self, command: str, reason: str) -> bool:
        if self.auto_approve:
            return True
        normalized = " ".join(command.strip().lower().split())
        if normalized in self.always_allowed:
            return True
        answer = await print_approval_prompt(command, reason)
        if answer == "A":
            self.always_allowed.add(normalized)
            return True
        return answer.lower() in {"a", "y", "yes"}


class ReplSession:
    def __init__(
        self,
        config: AppConfig,
        llm_client: BaseLLMClient,
        tool_registry: ToolRegistry,
        project_root: Path,
        auto_approve: bool = False,
    ) -> None:
        self.config = config
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.project_root = project_root.resolve()
        self.prompt_builder = PromptBuilder()
        self.approval_handler = ReplApprovalHandler(auto_approve=auto_approve)

        from code_agent.skills import BUNDLED_SKILLS_DIR
        project_skills = Path(config.skills.directory)
        if not project_skills.is_absolute():
            project_skills = (self.project_root / project_skills).resolve()
        personal_skills = Path.home() / ".code-agent" / "skills"
        self.skill_loader = SkillLoader(personal_skills, project_skills, BUNDLED_SKILLS_DIR)

        project_agents = self.project_root / ".code-agent" / "agents"
        personal_agents = Path.home() / ".code-agent" / "agents"
        self.agent_loader = AgentLoader(personal_agents, project_agents, BUNDLED_AGENTS_DIR)

        self.messages: list[dict[str, Any]] = []
        self.files_changed: set[str] = set()
        self.commands_run: list[str] = []
        self.step_count = 0
        self.selected_skill: str | None = None
        self.plan_mode: bool = False
        self.current_session_id: str | None = None
        self._skill_allowed_tools: list[str] | None = None

        # 初始化文件历史管理器
        from code_agent.services.file_history import FileHistoryManager
        import uuid
        session_id = str(uuid.uuid4())[:8]
        backup_root = self.project_root / ".code-agent" / "backups"
        self.file_history = FileHistoryManager(backup_root, session_id)

        self._init_system_prompt()

    async def recreate_llm_client(self) -> None:
        await self.llm_client.close()
        from code_agent.llm import create_llm_client

        self.llm_client = create_llm_client(self.config.model)

    async def switch_model(self, arg: str) -> None:
        """预设名：合并配置并重建客户端；否则仅视为裸 model_name。"""
        key = arg.strip()
        m = self.config.model
        if key in m.presets:
            apply_model_preset(m, key)
            await self.recreate_llm_client()
            return
        m.model_name = key
        client = self.llm_client
        if hasattr(client, "config"):
            cfg = client.config
            cfg.model_name = key
            cfg.provider = m.provider
            cfg.base_url = m.base_url
            cfg.api_key = m.api_key
            cfg.timeout_seconds = m.timeout_seconds

    def _init_system_prompt(self) -> None:
        context = self._make_context()
        prompt = self.prompt_builder.build_system_prompt(context)
        self.messages.append({"role": "system", "content": prompt})

    def refresh_system_prompt(self) -> None:
        context = self._make_context()
        prompt = self.prompt_builder.build_system_prompt(context)
        for i, msg in enumerate(self.messages):
            if msg.get("role") == "system":
                self.messages[i] = {"role": "system", "content": prompt}
                return
        self.messages.insert(0, {"role": "system", "content": prompt})

    def replace_system_from_workspace(self) -> None:
        """用当前项目与配置重建第一条 system（恢复会话后同步 AGENT.md / skill）。"""
        context = self._make_context()
        prompt = self.prompt_builder.build_system_prompt(context)
        for i, msg in enumerate(self.messages):
            if msg.get("role") == "system":
                self.messages[i] = {"role": "system", "content": prompt}
                return
        self.messages.insert(0, {"role": "system", "content": prompt})

    def save_conversation(self, title: str | None) -> str:
        from code_agent.services.session_storage import save_session_payload

        sid = save_session_payload(
            self.project_root,
            session_id=self.current_session_id,
            title=title,
            messages=self.messages,
            model_name=self.config.model.model_name or "",
            files_changed=sorted(self.files_changed),
            commands_run=list(self.commands_run),
            selected_skill=self.selected_skill,
            plan_mode=self.plan_mode,
            tool_max_chars=self.config.context.tool_message_max_chars,
        )
        self.current_session_id = sid
        return sid

    def load_conversation(self, payload: dict[str, Any]) -> str | None:
        """加载存档消息与状态；返回非空时表示跨项目警告文案。"""
        pr = payload.get("project_root") or ""
        warn: str | None = None
        if pr:
            try:
                if Path(pr).resolve() != self.project_root:
                    warn = f"该会话保存在其它项目目录：{pr}（已按当前项目继续）。"
            except OSError:
                warn = "无法校验原项目路径（已加载对话）。"
        self.messages.clear()
        self.messages.extend(copy.deepcopy(payload.get("messages") or []))
        self.files_changed = set(payload.get("files_changed") or [])
        self.commands_run = list(payload.get("commands_run") or [])
        self.selected_skill = payload.get("selected_skill")
        self.plan_mode = bool(payload.get("plan_mode", False))
        self.current_session_id = payload.get("id")
        self.step_count = 0
        self.replace_system_from_workspace()
        return warn

    def _make_context(self) -> AgentContext:
        ctx = AgentContext(
            config=self.config,
            project_root=self.project_root,
            path_guard=PathGuard(self.project_root, self.config.project.ignore_patterns),
            command_guard=CommandGuard(self.config.command_policy),
            skill_loader=self.skill_loader,
            approval_handler=self.approval_handler,
            agent_loader=self.agent_loader,
            _tool_registry=self.tool_registry,
            selected_skill=self.selected_skill,
        )
        # 传递plan_mode状态
        ctx.plan_mode = self.plan_mode
        # 传递file_history和session引用
        ctx.file_history = self.file_history
        ctx.session = self
        return ctx

    async def start(self) -> None:
        print_welcome(
            str(self.project_root),
            self.config.model.model_name,
            self.config.model.provider,
        )

        history_dir = self.project_root / ".code-agent"
        history_dir.mkdir(exist_ok=True)
        history_file = history_dir / "history"

        slash_names = sorted(cmd_mod.all_commands().keys())

        # 构建skills列表和描述字典（不包含bundled skills）
        skill_names = []
        skill_meta = {}
        for s in self.skill_loader.list_skills(include_bundled=False):
            if s.meta and not s.meta.user_invocable:
                continue
            skill_name = f"/{s.name}"
            skill_names.append(skill_name)
            skill_meta[skill_name] = s.preview  # 使用preview作为描述

        # 构建命令描述字典
        command_meta = cmd_mod.all_commands()  # 返回 {name: description}

        model_preset_words = [f"/model {k}" for k in sorted(self.config.model.presets.keys())]

        # 合并所有补全项和描述
        all_words = slash_names + skill_names + model_preset_words
        all_meta = {**command_meta, **skill_meta}

        completer = WordCompleter(
            all_words,
            sentence=True,
            meta_dict=all_meta,  # 添加描述字典
        )

        prompt_session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=completer,
        )

        while True:
            try:
                user_input = await prompt_session.prompt_async(
                    "> ",
                    multiline=False,
                )
            except (EOFError, KeyboardInterrupt):
                print_info("\n再见！")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            try:
                if user_input.startswith("/"):
                    await self._handle_slash(user_input)
                else:
                    await self._run_turn(user_input)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("REPL 执行失败")
                msg = str(exc).strip() or type(exc).__name__
                print_error(f"执行出错: {msg}")
                print_info("详情已写入日志，可继续输入。")

    async def _handle_slash(self, raw: str) -> None:
        parts = raw.split(maxsplit=1)
        cmd_name = parts[0].lower()
        args_str = parts[1] if len(parts) > 1 else ""
        args = args_str.split() if args_str else []

        entry = cmd_mod.get_handler(cmd_name)
        if entry is not None:
            _, handler, is_async = entry
            if is_async:
                await handler(self, args)
            else:
                handler(self, args)
            return

        skill_name = cmd_name.lstrip("/")
        await self._invoke_skill(skill_name, args_str)

    async def _invoke_skill(self, skill_name: str, arguments: str) -> None:
        from code_agent.skills.loader import render_skill_content

        try:
            meta, body = self.skill_loader.read_skill_parsed(skill_name)
        except FileNotFoundError:
            print_warning(f"未知命令或技能: /{skill_name}，输入 /help 查看可用命令。")
            return

        if meta and not meta.user_invocable:
            print_warning(f"技能 '{skill_name}' 不支持手动调用。")
            return

        # context: fork — 以独立 subagent 执行，skill body 作为其 system prompt
        if meta and meta.context == "fork":
            await self._invoke_skill_as_fork(skill_name, meta, body, arguments)
            return

        rendered = render_skill_content(body, arguments)
        print_info(f"⚡ 调用技能: {skill_name}" + (f" ({arguments})" if arguments else ""))

        self.selected_skill = skill_name
        # allowed-tools frontmatter 约束当前 skill 执行期间的工具集
        self._skill_allowed_tools = meta.allowed_tools if (meta and meta.allowed_tools) else None
        self.refresh_system_prompt()
        try:
            await self._run_turn(rendered)
        finally:
            self._skill_allowed_tools = None

    async def _invoke_skill_as_fork(
        self, skill_name: str, meta: Any, body: str, arguments: str
    ) -> None:
        """context: fork 模式 — 将 skill 以独立 subagent 运行。

        类似 claude-code 的 AgentTool + fork context：
        - skill body 作为 subagent 的 system prompt
        - allowed-tools frontmatter 约束工具集
        - 结果以普通 assistant 消息返回到主会话
        """
        from code_agent.agents.loader import AgentDef
        from code_agent.skills.loader import render_skill_content
        from code_agent.tools.agent_tools import DelegateAgentTool

        rendered_system = render_skill_content(body, arguments)
        task_prompt = arguments or f"请执行技能 {skill_name} 的任务。"

        allowed_tools: list[str] = meta.allowed_tools if meta and meta.allowed_tools else []
        model_override: str = meta.model if meta and meta.model else ""

        agent_def = AgentDef(
            name=f"skill:{skill_name}",
            description=f"Fork subagent for skill {skill_name}",
            system_prompt=rendered_system,
            tools=allowed_tools or None,
            disallowed_tools=[],
            model=model_override or None,
            max_turns=self.config.agent.max_steps,
        )

        print_info(f"⚡ 调用技能 (fork): {skill_name}" + (f" ({arguments})" if arguments else ""))

        context = self._make_context()
        context.messages = self.messages
        context.files_changed = self.files_changed
        context.commands_run = self.commands_run

        tool = DelegateAgentTool()
        result = await tool._run_sub_agent(agent_def, task_prompt, context)

        answer = result.content if result.ok else (result.error or "fork subagent 执行失败")
        self.messages.append({"role": "assistant", "content": answer})
        from code_agent.repl.renderer import print_text_chunk, print_text_end
        print_text_chunk("\n" + answer)
        print_text_end()

    _READONLY_TOOLS = {
        "list_files", "read_file", "find_files", "glob_files", "search_text",
        "list_skills", "read_skill", "invoke_skill", "preview_diff",
        "list_agents", "delegate_agent",
        # 任务管理（只读）
        "task_list", "task_get",
        # 用户交互
        "ask_user_question",
        # 计划模式控制
        "exit_plan_mode",
    }

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        schemas = self.tool_registry.tool_schemas()
        if self.plan_mode:
            schemas = [s for s in schemas if s["function"]["name"] in self._READONLY_TOOLS]
        # skill 级别的 allowed-tools 约束（frontmatter: allowed-tools）
        allowed = getattr(self, "_skill_allowed_tools", None)
        if allowed:
            schemas = [s for s in schemas if s["function"]["name"] in allowed]
        return schemas

    async def compact_conversation_llm(self) -> Literal["llm_ok", "crude_ok", "skipped"]:
        """模型摘要压缩；失败则回退粗粒度 apply_compact。"""
        try:
            new_msgs, ok = await apply_compact_llm(self.messages, self.llm_client, self.config)
            if ok:
                self.messages.clear()
                self.messages.extend(new_msgs)
                return "llm_ok"
        except Exception as exc:
            logger.warning("LLM compact failed: %s", exc)
        kr = self.config.context.compact_keep_recent
        new_msgs, changed = apply_compact(self.messages, keep_recent=kr)
        if changed:
            self.messages.clear()
            self.messages.extend(new_msgs)
            return "crude_ok"
        return "skipped"

    async def _maybe_shrink_context(self) -> None:
        """估算 token，必要时截断历史 tool 文本、自动 compact 或提示用户。"""
        ctx = self.config.context
        truncate_tool_messages_in_history(self.messages, ctx.tool_message_max_chars)
        est = estimate_messages_tokens(self.messages)
        compacted = False
        if ctx.budget_tokens_compact > 0 and est >= ctx.budget_tokens_compact and len(self.messages) > 4:
            if ctx.compact_auto_use_llm:
                mode = await self.compact_conversation_llm()
                if mode in ("llm_ok", "crude_ok"):
                    compacted = True
                    print_info(
                        f"上下文估算约 {est} tokens，已自动压缩（"
                        f"{'模型摘要' if mode == 'llm_ok' else '粗粒度'}，"
                        f"可调整 context.budget_tokens_compact / compact_auto_use_llm）。"
                    )
            else:
                new_msgs, changed = apply_compact(self.messages, keep_recent=ctx.compact_keep_recent)
                if changed:
                    self.messages.clear()
                    self.messages.extend(new_msgs)
                    print_info(
                        f"上下文估算约 {est} tokens，已自动压缩（可调整 config 中 context.budget_tokens_compact）。"
                    )
                    compacted = True
        if not compacted and est >= ctx.budget_tokens_warn:
            print_warning(
                f"上下文估算约 {est} tokens，接近模型上限，建议 /compact 或分批读文件。"
            )

    def _tool_content_for_history(self, text: str) -> str:
        return truncate_tool_content(text, self.config.context.tool_message_max_chars)

    async def _run_turn(self, user_input: str) -> None:
        if self.plan_mode:
            user_input = (
                f"[Plan 模式] {user_input}\n\n"
                "你当前处于 Plan 模式：只能读取和研究代码，不能修改文件或执行命令。"
                "请分析问题，提出详细的实施方案，列出需要修改的文件和步骤，等待用户确认后再执行。"
            )

        self.messages.append({"role": "user", "content": user_input})
        await self._maybe_shrink_context()
        context = self._make_context()
        context.messages = self.messages
        context.files_changed = self.files_changed
        context.commands_run = self.commands_run

        tool_failures = 0

        for step in range(self.config.agent.max_steps):
            self.step_count += 1
            _trim_context(self.messages)
            truncate_tool_messages_in_history(
                self.messages, self.config.context.tool_message_max_chars
            )

            text_parts: list[str] = []
            tool_calls_raw: list[dict[str, str]] = []
            had_text = False

            async for chunk in self.llm_client.chat_stream(
                self.messages, self._get_tool_schemas()
            ):
                if chunk.type == "text_delta":
                    if not had_text:
                        print_text_chunk("\n")
                        had_text = True
                    print_text_chunk(chunk.text)
                    text_parts.append(chunk.text)

                elif chunk.type == "tool_call":
                    tool_calls_raw.append({
                        "id": chunk.tool_call_id,
                        "name": chunk.tool_name,
                        "arguments": chunk.tool_arguments_delta,
                    })

                elif chunk.type == "done":
                    if had_text:
                        print_text_end()

            full_text = "".join(text_parts)

            if not tool_calls_raw:
                self.messages.append({"role": "assistant", "content": full_text})
                return

            assistant_tool_calls = []
            for idx, tc in enumerate(tool_calls_raw):
                tool_call_id = tc["id"] or f"call_{self.step_count}_{idx + 1}"
                assistant_tool_calls.append({
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                })
            self.messages.append({
                "role": "assistant",
                "content": full_text,
                "tool_calls": assistant_tool_calls,
            })

            for idx, tc in enumerate(tool_calls_raw):
                tool_call_id = tc["id"] or f"call_{self.step_count}_{idx + 1}"
                name = tc["name"]
                try:
                    arguments = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    arguments = {}

                print_tool_call(name, arguments)

                if name == "run_command":
                    command = arguments.get("command", "")
                    reason = arguments.get("reason", "")
                    try:
                        parsed = context.command_guard.parse(command)
                    except ValueError as exc:
                        tool_failures += 1
                        self.messages.append({
                            "role": "tool", "tool_call_id": tool_call_id,
                            "content": self._tool_content_for_history(f"Invalid command: {exc}"),
                        })
                        print_tool_result(name, False, str(exc))
                        continue
                    decision = context.command_guard.decide(command)
                    if decision == CommandDecision.DENY:
                        self.messages.append({
                            "role": "tool", "tool_call_id": tool_call_id,
                            "content": self._tool_content_for_history(f"command denied by policy: {command}"),
                        })
                        print_tool_result(name, False, f"denied: {command}")
                        continue
                    if decision == CommandDecision.REQUIRE_APPROVAL:
                        if not await self.approval_handler.is_approved(command, reason):
                            self.messages.append({
                                "role": "tool", "tool_call_id": tool_call_id,
                                "content": self._tool_content_for_history(f"command rejected by user: {command}"),
                            })
                            print_tool_result(name, False, "用户拒绝执行")
                            continue
                        context.pre_approved_commands.add(parsed.normalized)

                try:
                    result = self.tool_registry.execute(name, arguments, context)
                except Exception as exc:
                    tool_failures += 1
                    logger.exception("tool %s raised", name)
                    err_text = format_tool_error_for_model(str(exc))
                    self.messages.append({
                        "role": "tool", "tool_call_id": tool_call_id,
                        "content": self._tool_content_for_history(f"Tool failed: {err_text}"),
                    })
                    print_tool_result(name, False, err_text)
                    continue

                if not result.ok:
                    tool_failures += 1
                raw = result.content if result.ok else (result.error or "tool failed")
                if not result.ok:
                    raw = format_tool_error_for_model(str(raw))
                self.messages.append({
                    "role": "tool", "tool_call_id": tool_call_id,
                    "content": self._tool_content_for_history(str(raw)),
                })
                print_tool_result(name, result.ok, result.content if result.ok else (result.error or "failed"))

            if tool_failures >= self.config.agent.max_tool_failures:
                print_error("工具调用失败次数过多，本轮停止。")
                # 创建快照
                self.file_history.make_snapshot(len(self.messages))
                return

        print_warning("达到最大步数，本轮停止。")
        # 创建快照
        self.file_history.make_snapshot(len(self.messages))

    async def run_team(self, task: str) -> None:
        from code_agent.app import build_team_orchestrator
        print_team_header(task)
        orch = build_team_orchestrator(self.config)
        try:
            result = await orch.run(task, self.project_root)
        except Exception as exc:
            print_error(f"Team 执行失败: {exc}")
            return
        finally:
            await orch.llm_client.close()

        for r in result.sub_results:
            print_sub_agent_start(r.role, r.task)
            print_sub_agent_done(r.role, r.result.final_answer)

        if result.summary:
            print_text_chunk("\n")
            from code_agent.repl.renderer import print_markdown
            print_markdown(result.summary)
            print_text_chunk("\n")
        if result.decision or result.confidence or result.recommended_next_step:
            from code_agent.repl.renderer import console
            lines = []
            if result.decision:
                lines.append(f"[bold]Decision:[/bold] {result.decision}")
            if result.confidence:
                lines.append(f"[bold]Confidence:[/bold] {result.confidence}")
            if result.recommended_next_step:
                lines.append(f"[bold]Next:[/bold] {result.recommended_next_step}")
            if result.open_questions:
                lines.append("[bold]Open Questions:[/bold]")
                lines.extend(f"- {item}" for item in result.open_questions[:5])
            console.print("\n".join(lines))
            print_text_chunk("\n")

        self.files_changed.update(result.all_files_changed)
        self.commands_run.extend(result.all_commands_run)


def _trim_context(messages: list[dict[str, Any]]) -> None:
    if len(messages) <= MAX_CONTEXT_MESSAGES:
        return
    preserved = list(messages[:2])
    recent = messages[-TRIM_KEEP_RECENT:]
    messages.clear()
    messages.extend(preserved + recent)
