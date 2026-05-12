from __future__ import annotations

import locale
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from code_agent.schemas import CommandDecision, PendingApproval, ToolResult
from code_agent.tools.base import BaseTool

_FALLBACK_ENCODINGS = ["utf-8", "gbk", "utf-8-sig", "latin-1"]
_IS_WINDOWS = sys.platform == "win32"


def _decode_bytes(raw: bytes) -> str:
    """尝试多种编码依次解码，最终兜底 latin-1（不会失败）。"""
    system_enc = locale.getpreferredencoding(False)
    candidates = [system_enc] + [e for e in _FALLBACK_ENCODINGS if e != system_enc]
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


def _find_windows_shell() -> tuple[str, str]:
    """
    返回 (shell_type, shell_path)。
    优先级：pwsh(7+) → powershell(5.1) → cmd
    pwsh/powershell 用 -NonInteractive -Command，不受 ExecutionPolicy 影响（只拦 .ps1 脚本）。
    cmd 作为最终兜底，适合公司完全禁用 PowerShell 的场景。
    """
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            return ("ps", path)
    cmd = shutil.which("cmd") or "cmd"
    return ("cmd", cmd)


def _build_shell_argv(command: str) -> list[str]:
    """
    将命令字符串包装进 shell 进程的 argv。

    Windows:
      PowerShell（优先）: pwsh/powershell -NoProfile -NonInteractive -Command <cmd>
        - 支持 &&（PS 7+）、App Execution Alias、UTF-8 输出
        - -NonInteractive + -Command 不受 ExecutionPolicy Restricted 影响
      cmd（兜底）: cmd /c <cmd>
        - 支持 &&、App Execution Alias、兼容性最强
        - 输出为系统 GBK 编码（_decode_bytes 会自动处理）
        - 不支持 PowerShell 特有语法（$var、Get-* cmdlet）

    Unix: bash -c <cmd>（或回退到 sh -c）
    """
    if _IS_WINDOWS:
        shell_type, shell_path = _find_windows_shell()
        if shell_type == "ps":
            return [shell_path, "-NoProfile", "-NonInteractive", "-Command", command]
        # cmd 兜底：/c 执行命令后退出
        return [shell_path, "/c", command]
    bash = shutil.which("bash") or shutil.which("sh") or "sh"
    return [bash, "-c", command]


class RunCommandTool(BaseTool):
    name = "run_command"
    description = (
        "执行一个受策略控制的本地命令。"
        "支持 working_dir 参数指定工作目录（相对路径视为相对于项目根目录）。"
        "cd 命令会更新会话工作目录，后续命令在新目录中执行。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "reason": {"type": "string"},
            "working_dir": {
                "type": "string",
                "description": "命令执行目录，留空则使用当前会话目录。",
            },
        },
        "required": ["command"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        command = arguments["command"]
        reason = arguments.get("reason", "model requested command execution")
        working_dir_arg: str | None = arguments.get("working_dir")

        parsed = context.command_guard.parse(command)
        decision = context.command_guard.decide(command)
        normalized = parsed.normalized

        if decision == CommandDecision.DENY:
            return ToolResult(ok=False, content="", error=f"command denied by policy: {command}")

        if decision == CommandDecision.REQUIRE_APPROVAL:
            if normalized in getattr(context, "pre_approved_commands", set()):
                pass
            elif not context.approval_handler.is_approved(command, reason):
                pending = PendingApproval(command=command, reason=reason)
                context.pending_approval = pending
                return ToolResult(
                    ok=False,
                    content="",
                    error=f"command requires approval: {command}",
                    metadata={"pending_approval": pending},
                )

        # cd 命令：更新会话工作目录，不真正 fork 进程
        if parsed.argv and parsed.argv[0].lower() == "cd" and len(parsed.argv) >= 2:
            return self._handle_cd(parsed.argv[1], context)

        # 计算实际 cwd
        cwd = self._resolve_cwd(context, working_dir_arg)

        proc = subprocess.run(
            _build_shell_argv(command),
            cwd=cwd,
            shell=False,
            capture_output=True,
            timeout=context.config.tools.command_timeout_seconds,
            check=False,
        )
        stdout = _decode_bytes(proc.stdout)
        stderr = _decode_bytes(proc.stderr)
        output = (stdout + ("\n" + stderr if stderr.strip() else "")).strip()
        if len(output) > context.config.tools.command_output_max_chars:
            output = output[: context.config.tools.command_output_max_chars] + "\n...[truncated]"
        context.commands_run.append(command)

        cwd_info = f"[cwd: {cwd}]\n" if cwd != context.project_root else ""
        return ToolResult(
            ok=proc.returncode == 0,
            content=cwd_info + output,
            metadata={"exit_code": proc.returncode, "cwd": str(cwd)},
            error=None if proc.returncode == 0 else f"command exited with code {proc.returncode}",
        )

    def _handle_cd(self, target: str, context: Any) -> ToolResult:
        current = getattr(context, "shell_cwd", None) or context.project_root
        new_dir = (current / target).resolve()
        try:
            context.path_guard.ensure_allowed(str(new_dir))
        except Exception as exc:
            return ToolResult(ok=False, content="", error=f"cd 被路径策略拒绝: {exc}")
        if not new_dir.is_dir():
            return ToolResult(ok=False, content="", error=f"目录不存在: {new_dir}")
        context.shell_cwd = new_dir
        return ToolResult(ok=True, content=f"工作目录已切换到: {new_dir}")

    def _resolve_cwd(self, context: Any, working_dir_arg: str | None) -> Path:
        if working_dir_arg:
            p = Path(working_dir_arg)
            if not p.is_absolute():
                p = (context.project_root / p).resolve()
            return p
        return getattr(context, "shell_cwd", None) or context.project_root
