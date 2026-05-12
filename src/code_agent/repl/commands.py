from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from code_agent.repl.session import ReplSession

CommandHandler = Callable[["ReplSession", list[str]], Any]

_COMMANDS: dict[str, tuple[str, CommandHandler, bool]] = {}


def register(name: str, description: str, is_async: bool = False) -> Callable[[CommandHandler], CommandHandler]:
    def decorator(func: CommandHandler) -> CommandHandler:
        _COMMANDS[name] = (description, func, is_async)
        return func
    return decorator


def get_handler(name: str) -> tuple[str, CommandHandler, bool] | None:
    return _COMMANDS.get(name)


def all_commands() -> dict[str, str]:
    return {name: desc for name, (desc, _, _) in sorted(_COMMANDS.items())}


@register("/help", "显示帮助信息")
def cmd_help(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console
    lines = ["[bold]内置命令:[/bold]\n"]
    for name, desc in all_commands().items():
        lines.append(f"  [cyan]{name:<12}[/cyan] {desc}")
    console.print("\n".join(lines))

    skills = session.skill_loader.list_skills()
    invocable = [s for s in skills if not (s.meta and not s.meta.user_invocable)]
    if invocable:
        console.print()
        console.print("[bold]可用技能 (直接 /名称 调用):[/bold]\n")
        for s in invocable:
            hint = f" {s.meta.argument_hint}" if s.meta and s.meta.argument_hint else ""
            console.print(f"  [cyan]/{s.name}{hint:<8}[/cyan] {s.preview}")

    agents = session.agent_loader.list_agents()
    if agents:
        console.print()
        console.print("[bold]可用子 Agent (LLM 可自动委派):[/bold]\n")
        for a in agents:
            console.print(f"  [cyan]{a.name:<16}[/cyan] {a.description}")
    console.print()


@register("/clear", "清空对话历史")
def cmd_clear(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import print_info
    session.messages.clear()
    session.files_changed.clear()
    session.commands_run.clear()
    session.step_count = 0
    session.selected_skill = None
    session.current_session_id = None
    session._init_system_prompt()
    print_info("对话历史已清空。")


@register("/status", "当前会话状态")
def cmd_status(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console
    from rich.panel import Panel
    model = session.config.model.model_name or "mock"
    mode = "[yellow]Plan (只读)[/yellow]" if getattr(session, "plan_mode", False) else "[green]Agent (完整)[/green]"
    sid = getattr(session, "current_session_id", None)
    sid_line = f"存档 id: [cyan]{sid[:8]}…[/cyan] ({sid})" if sid else "存档 id: [dim]未绑定（/save 后会有）[/dim]"
    lines = [
        f"模式: {mode}",
        f"模型: [cyan]{model}[/cyan]",
        f"Provider: {session.config.model.provider}",
        sid_line,
        f"项目: {session.project_root}",
        f"对话轮数: {session.step_count}",
        f"消息数: {len(session.messages)}",
        f"修改文件: {len(session.files_changed)}",
        f"执行命令: {len(session.commands_run)}",
    ]
    console.print(Panel("\n".join(lines), title="会话状态", border_style="blue", padding=(0, 2)))


@register("/cost", "查看 Token 用量")
def cmd_cost(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import print_cost
    client = session.llm_client
    input_t = getattr(client, "total_input_tokens", 0)
    output_t = getattr(client, "total_output_tokens", 0)
    print_cost(input_t, output_t)


@register("/tools", "列出可用工具")
def cmd_tools(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console
    names = session.tool_registry.list_names()
    console.print("[bold]可用工具:[/bold]")
    for name in names:
        tool = session.tool_registry.get(name)
        console.print(f"  [cyan]{name:<20}[/cyan] {tool.description}")
    console.print()


@register("/skill", "技能管理: /skill list | /skill use <name> | /skill clear")
def cmd_skill(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console, print_info, print_warning

    sub = args[0].lower() if args else "list"

    if sub == "list":
        skills = session.skill_loader.list_skills()
        if not skills:
            console.print("[dim]暂无可用 skill。在 skills/ 目录下创建 <name>/SKILL.md 即可添加。[/dim]")
            return
        current = session.selected_skill
        console.print("[bold]可用技能:[/bold]")
        for s in skills:
            marker = " [green]◀ 当前[/green]" if s.name == current else ""
            console.print(f"  [cyan]{s.name:<20}[/cyan] {s.preview}{marker}")
        console.print()

    elif sub == "use":
        if len(args) < 2:
            print_warning("用法: /skill use <技能名称>")
            return
        name = args[1]
        try:
            session.skill_loader.read_skill(name)
        except FileNotFoundError:
            print_warning(f"技能 '{name}' 不存在，输入 /skill list 查看可用技能。")
            return
        session.selected_skill = name
        session.refresh_system_prompt()
        print_info(f"已启用技能: {name}，后续对话将使用此技能的指令。")

    elif sub == "clear":
        if session.selected_skill:
            old = session.selected_skill
            session.selected_skill = None
            session.refresh_system_prompt()
            print_info(f"已取消技能: {old}")
        else:
            print_info("当前没有启用任何技能。")

    else:
        print_warning("用法: /skill list | /skill use <name> | /skill clear")


@register("/model", "切换模型: /model 交互选预设 | /model <预设名或模型 id>", is_async=True)
async def cmd_model(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console, interactive_select, print_info

    presets = session.config.model.presets
    if not args:
        m = session.config.model
        current = m.model_name or "(空)"
        console.print(
            f"当前: [cyan]{current}[/cyan]  ·  provider: {m.provider}"
        )
        if m.base_url:
            console.print(f"base_url: [dim]{m.base_url}[/dim]")
        if not presets:
            console.print(
                "[dim]未配置 model.presets。在 YAML 的 model.presets 下添加别名，"
                "或直接使用 /model 加空格加网关上的模型 id。[/dim]"
            )
            return
        options: list[tuple[str, str]] = []
        for key in sorted(presets.keys()):
            p = presets[key]
            mn = p.model_name or current
            desc = f" ({p.description})" if p.description else ""
            url_hint = ""
            if p.base_url:
                host = p.base_url.replace("https://", "").replace("http://", "").split("/")[0]
                if len(host) > 42:
                    host = host[:39] + "…"
                url_hint = f" · {host}"
            options.append((key, f"{key}  →  {mn}{desc}{url_hint}"))
        console.print("\n[bold]选择预设[/bold]（↑↓ / Enter，Esc 取消）\n")
        choice = await interactive_select(options)
        if choice is None:
            print_info("已取消。")
            return
        old = m.model_name
        await session.switch_model(choice)
        print_info(f"已切换到预设 [cyan]{choice}[/cyan]: {old or 'mock'} → {session.config.model.model_name}")
        return

    arg = " ".join(args).strip()
    old = session.config.model.model_name
    await session.switch_model(arg)
    if arg in presets:
        print_info(f"已切换到预设 [cyan]{arg}[/cyan]: {old or 'mock'} → {session.config.model.model_name}")
    else:
        print_info(f"模型名已更新: {old or 'mock'} → {session.config.model.model_name}")


@register("/compact", "压缩对话上下文（优先模型摘要）", is_async=True)
async def cmd_compact(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import print_info, print_warning

    before = len(session.messages)
    mode = await session.compact_conversation_llm()
    if mode == "llm_ok":
        print_info(
            f"已用模型生成摘要并压缩上下文: {before} → {len(session.messages)} 条消息。"
        )
    elif mode == "crude_ok":
        print_warning(
            f"模型摘要不可用，已使用保守压缩: {before} → {len(session.messages)} 条消息。"
        )
    else:
        print_info("对话太短，无需压缩。")


@register("/team", "Agent Teams: /team <任务>", is_async=True)
async def cmd_team(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import print_warning

    if not args:
        print_warning("用法: /team <任务描述>")
        return

    task = " ".join(args).strip()
    if not task:
        print_warning("用法: /team <任务描述>")
        return
    await session.run_team(task)


@register("/agents", "查看/管理子 agent: /agents list | /agents info <name>")
def cmd_agents(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console, print_warning

    sub = args[0].lower() if args else "list"

    if sub == "list":
        agents = session.agent_loader.list_agents()
        if not agents:
            console.print("[dim]暂无可用 agent。在 .code-agent/agents/ 目录下创建 .md 文件即可添加。[/dim]")
            return
        console.print("[bold]可用子 Agent:[/bold]\n")
        for a in agents:
            tools_str = ", ".join(a.tools) if a.tools else "全部工具"
            src_tag = "[dim](内置)[/dim]" if "bundled" in a.source else ""
            console.print(f"  [cyan]{a.name:<16}[/cyan] {a.description} {src_tag}")
            console.print(f"  {'':16} [dim]工具: {tools_str} | 最大轮数: {a.max_turns}[/dim]")
        console.print()

    elif sub == "info":
        if len(args) < 2:
            print_warning("用法: /agents info <agent名称>")
            return
        name = args[1]
        agent_def = session.agent_loader.get_agent(name)
        if agent_def is None:
            print_warning(f"agent '{name}' 不存在，输入 /agents list 查看可用列表。")
            return
        from rich.panel import Panel
        lines = [
            f"[bold]名称:[/bold] {agent_def.name}",
            f"[bold]描述:[/bold] {agent_def.description}",
            f"[bold]工具:[/bold] {', '.join(agent_def.tools) or '全部'}",
            f"[bold]禁用工具:[/bold] {', '.join(agent_def.disallowed_tools) or '无'}",
            f"[bold]模型:[/bold] {agent_def.model or '继承主模型'}",
            f"[bold]最大轮数:[/bold] {agent_def.max_turns}",
            f"[bold]技能:[/bold] {', '.join(agent_def.skills) or '无'}",
        ]
        if agent_def.system_prompt:
            lines.append(f"\n[bold]系统提示:[/bold]\n{agent_def.system_prompt[:500]}")
        console.print(Panel("\n".join(lines), title=f"Agent: {name}", border_style="cyan", padding=(0, 2)))

    else:
        print_warning("用法: /agents list | /agents info <name>")


@register("/sessions", "会话存档: /sessions list | /sessions delete <id前缀>")
def cmd_sessions(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console, print_info, print_warning
    from code_agent.services import session_storage as ss

    sub = args[0].lower() if args else "list"

    if sub == "list" or not args:
        rows = ss.list_sessions(session.project_root)
        if not rows:
            console.print("[dim]暂无已保存会话。使用 /save 保存当前对话。[/dim]")
            return
        console.print("[bold]已保存的会话[/bold]（`project/.code-agent/sessions/*.json`）\n")
        for r in rows:
            short = r.session_id[:8]
            console.print(
                f"  [cyan]{short}…[/cyan]  {r.title}\n"
                f"    [dim]id={r.session_id}  ·  {r.updated_at[:19]}  ·  {r.message_count} 条消息[/dim]"
            )
        console.print()
        return

    if sub == "delete":
        if len(args) < 2:
            print_warning("用法: /sessions delete <id前缀>")
            return
        q = " ".join(args[1:])
        if ss.delete_session(session.project_root, q):
            print_info("已删除该会话文件。")
            if session.current_session_id and (
                session.current_session_id.startswith(q) or q in session.current_session_id
            ):
                session.current_session_id = None
        else:
            print_warning("未唯一匹配到会话，请用 /sessions list 查看完整 id。")
        return

    print_warning("用法: /sessions list | /sessions delete <id前缀>")


@register("/save", "保存对话到本地: /save [标题]")
def cmd_save(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import print_info, print_warning

    title = " ".join(args).strip() or None
    if len(session.messages) <= 1:
        print_warning("当前几乎没有对话内容，无需保存。")
        return
    sid = session.save_conversation(title)
    short = sid[:8]
    print_info(f"已保存会话 [cyan]{short}…[/cyan]  id={sid}\n再次保存将覆盖同一文件（/clear 后会新建 id）。")


@register("/resume", "恢复会话: /resume [id或关键词]，无参时交互选择", is_async=True)
async def cmd_resume(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console, interactive_select, print_info, print_warning
    from code_agent.services import session_storage as ss

    query = " ".join(args).strip()

    if not query:
        summaries = ss.list_sessions(session.project_root)
        if not summaries:
            print_info("暂无已保存会话。使用 /save 保存当前对话。")
            return
        options: list[tuple[str, str]] = []
        for s in summaries[:30]:
            label = f"{s.session_id[:8]}…  {s.title}  ·  {s.message_count} 条"
            options.append((s.session_id, label))
        console.print("\n[bold]选择要恢复的会话[/bold]（↑↓ / Enter，Esc 取消）\n")
        choice = await interactive_select(options)
        if choice is None:
            print_info("已取消。")
            return
        payload = ss.load_session_payload(session.project_root, choice)
    else:
        matches = ss.find_sessions_by_query(session.project_root, query)
        if not matches:
            print_warning("未找到匹配的会话。使用 /sessions list 查看。")
            return
        if len(matches) > 1:
            print_warning(f"匹配到 {len(matches)} 个会话，请使用更长前缀或 /resume 无参选择：\n")
            for m in matches[:12]:
                console.print(f"  [cyan]{m.session_id[:8]}…[/cyan]  {m.title}")
            return
        payload = ss.load_session_payload(session.project_root, matches[0].session_id)

    if not payload:
        print_warning("无法读取会话文件。")
        return
    warn = session.load_conversation(payload)
    if warn:
        print_warning(warn)
    cid = session.current_session_id or "?"
    print_info(
        f"已恢复会话 [cyan]{cid[:8]}…[/cyan]  "
        f"（{len(session.messages)} 条消息）。后续 /save 将更新此存档。"
    )




@register("/plan", "Plan 模式: 只研究不修改，先出方案再执行")
def cmd_plan(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import print_info
    session.plan_mode = not getattr(session, "plan_mode", False)
    if session.plan_mode:
        print_info(
            "已进入 Plan 模式\n"
            "  • LLM 只能使用只读工具（读文件、搜索、列文件）\n"
            "  • 不会写文件、执行命令\n"
            "  • 输出方案供你确认，确认后再 /plan 退出执行\n"
        )
    else:
        print_info("已退出 Plan 模式，恢复全部工具权限。")


@register("/quit", "退出")
def cmd_quit(session: ReplSession, args: list[str]) -> None:
    raise SystemExit(0)


@register("/undo", "撤销最近的文件修改")
def cmd_undo(session: ReplSession, args: list[str]) -> None:
    from code_agent.repl.renderer import console, print_error, print_info, print_warning

    # 检查是否有快照
    if not session.file_history.state.snapshots:
        print_warning("没有可撤销的修改。")
        return

    # 获取快照信息
    snapshot_info = session.file_history.get_snapshot_info(-2)  # 倒数第二个快照
    if not snapshot_info["exists"]:
        print_warning("没有可撤销的修改。")
        return

    # 显示将要恢复的文件
    console.print(f"\n[bold]将恢复到快照:[/bold]")
    console.print(f"  消息索引: {snapshot_info['message_index']}")
    console.print(f"  时间: {snapshot_info['timestamp']}")
    console.print(f"  涉及文件: {snapshot_info['tracked_files_count']} 个\n")

    if snapshot_info['tracked_files']:
        console.print("[bold]将恢复的文件:[/bold]")
        for file_path in snapshot_info['tracked_files'][:10]:
            console.print(f"  • {file_path}")
        if len(snapshot_info['tracked_files']) > 10:
            console.print(f"  ... 还有 {len(snapshot_info['tracked_files']) - 10} 个文件")
        console.print()

    # 执行恢复
    try:
        restored_files = session.file_history.rewind_to_snapshot(
            session.project_root, -2
        )
        if restored_files:
            print_info(f"已恢复 {len(restored_files)} 个文件到之前的状态。")
            # 更新files_changed
            session.files_changed.update(restored_files)
        else:
            print_info("没有文件需要恢复。")
    except Exception as exc:
        print_error(f"撤销失败: {exc}")
