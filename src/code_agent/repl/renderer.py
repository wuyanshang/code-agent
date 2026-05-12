from __future__ import annotations

import sys
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

THEME = Theme({
    "tool.name": "bold cyan",
    "tool.ok": "green",
    "tool.fail": "red",
    "info": "dim",
    "warn": "yellow",
    "agent.role": "bold magenta",
})

console = Console(theme=THEME, highlight=False)


def print_welcome(project: str, model: str, provider: str) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold]code-agent[/bold]  ·  model: [cyan]{model or 'mock'}[/cyan]  ·  provider: {provider}\n"
            f"project: [dim]{project}[/dim]\n\n"
            f"输入任务开始对话，输入 [bold]/help[/bold] 查看可用命令，[bold]/quit[/bold] 退出。",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()


def print_text_chunk(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def print_text_end() -> None:
    sys.stdout.write("\n\n")
    sys.stdout.flush()


def print_tool_call(name: str, arguments: dict[str, Any]) -> None:
    args_display = ", ".join(f"{k}={_short_val(v)}" for k, v in arguments.items())
    console.print(f"  [tool.name]⚡ {name}[/tool.name]({args_display})")


def print_tool_result(name: str, ok: bool, content: str) -> None:
    status = "[tool.ok]✓[/tool.ok]" if ok else "[tool.fail]✗[/tool.fail]"
    preview = content[:200].replace("\n", " ")
    if len(content) > 200:
        preview += "..."
    console.print(f"  {status} [dim]{preview}[/dim]")


def print_error(message: str) -> None:
    console.print(f"[tool.fail]✗ {message}[/tool.fail]")


def print_info(message: str) -> None:
    console.print(f"[info]{message}[/info]")


def print_warning(message: str) -> None:
    console.print(f"[warn]⚠ {message}[/warn]")


def print_agent_thinking() -> None:
    console.print("[dim]⠋ thinking...[/dim]")


def print_step_header(step: int) -> None:
    console.print(f"\n[dim]── step {step} ──[/dim]")


async def print_approval_prompt(command: str, reason: str) -> str:
    console.print()
    console.print(Panel(
        f"[bold]{command}[/bold]\n[dim]{reason}[/dim]",
        title="⚠ 需要执行命令",
        border_style="yellow",
        padding=(0, 2),
    ))
    options = [
        ("y", "本次允许"),
        ("A", "永久允许"),
        ("d", "拒绝"),
    ]
    result = await _interactive_select(options)
    return result or "d"


async def _interactive_select(options: list[tuple[str, str]]) -> str | None:
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    selected = [0]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _move_up(event: Any) -> None:
        selected[0] = (selected[0] - 1) % len(options)

    @kb.add("down")
    @kb.add("j")
    def _move_down(event: Any) -> None:
        selected[0] = (selected[0] + 1) % len(options)

    @kb.add("enter")
    def _confirm(event: Any) -> None:
        event.app.exit(result=options[selected[0]][0])

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event: Any) -> None:
        event.app.exit(result=None)

    def _get_text() -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        for i, (_, label) in enumerate(options):
            if i == selected[0]:
                lines.append(("class:highlight", f"  ❯ {label}\n"))
            else:
                lines.append(("", f"    {label}\n"))
        return lines

    control = FormattedTextControl(_get_text)
    window = Window(content=control, always_hide_cursor=True)

    style = Style.from_dict({
        "highlight": "bold cyan",
    })

    app: Application[str | None] = Application(
        layout=Layout(window),
        key_bindings=kb,
        style=style,
    )
    return await app.run_async()


async def interactive_select(options: list[tuple[str, str]]) -> str | None:
    """上下键选择，返回选项的 key（第一个元素），Escape 取消。"""
    return await _interactive_select(options)


def print_team_header(task: str) -> None:
    console.print(Panel(
        f"[bold]{task}[/bold]",
        title="🤖 Agent Teams",
        border_style="magenta",
        padding=(0, 2),
    ))


def print_sub_agent_start(role: str, task: str) -> None:
    console.print(f"\n[agent.role]▶ [{role}][/agent.role] {task[:100]}")


def print_sub_agent_done(role: str, answer: str) -> None:
    preview = answer[:300].replace("\n", " ")
    console.print(f"[agent.role]  ✓ [{role}][/agent.role] [dim]{preview}[/dim]")


def print_cost(input_tokens: int, output_tokens: int) -> None:
    total = input_tokens + output_tokens
    console.print(Panel(
        f"输入: [cyan]{input_tokens:,}[/cyan] tokens\n"
        f"输出: [cyan]{output_tokens:,}[/cyan] tokens\n"
        f"合计: [bold]{total:,}[/bold] tokens",
        title="Token 用量",
        border_style="dim",
        padding=(0, 2),
    ))


def print_markdown(text: str) -> None:
    console.print(Markdown(text))


def _short_val(v: Any) -> str:
    s = str(v)
    return s if len(s) <= 60 else s[:57] + "..."
