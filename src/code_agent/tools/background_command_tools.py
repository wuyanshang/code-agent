from __future__ import annotations

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool


@dataclass
class BackgroundTask:
    """后台任务信息"""

    task_id: str
    command: str
    status: Literal["running", "completed", "failed", "stopped"] = "running"
    output: str = ""
    error: str = ""
    exit_code: int | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    process: subprocess.Popen | None = None


class BackgroundCommandManager:
    """后台命令管理器（单例）"""

    _instance: BackgroundCommandManager | None = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.tasks: dict[str, BackgroundTask] = {}
        self._initialized = True

    def start_task(
        self,
        command: str,
        cwd: Path,
        timeout: int,
        shell: bool = False,
    ) -> str:
        """启动后台任务"""
        task_id = str(uuid.uuid4())[:8]

        # 解析命令
        if shell:
            cmd = command
        else:
            import shlex
            cmd = shlex.split(command, posix=False)

        # 创建任务
        task = BackgroundTask(
            task_id=task_id,
            command=command,
        )
        self.tasks[task_id] = task

        # 启动线程执行命令
        thread = threading.Thread(
            target=self._run_command,
            args=(task_id, cmd, cwd, timeout, shell),
            daemon=True,
        )
        thread.start()

        return task_id

    def _run_command(
        self,
        task_id: str,
        cmd: str | list[str],
        cwd: Path,
        timeout: int,
        shell: bool,
    ):
        """在后台线程中运行命令"""
        task = self.tasks[task_id]

        try:
            # 启动进程
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",  # 忽略编码错误
            )
            task.process = process

            # 等待完成或超时
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                task.output = stdout
                task.error = stderr
                task.exit_code = process.returncode
                task.status = "completed" if process.returncode == 0 else "failed"
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                task.output = stdout
                task.error = f"命令超时（>{timeout}秒）\n{stderr}"
                task.exit_code = -1
                task.status = "failed"

        except Exception as e:
            task.error = str(e)
            task.exit_code = -1
            task.status = "failed"

        finally:
            task.end_time = time.time()
            task.process = None

    def get_task(self, task_id: str) -> BackgroundTask | None:
        """获取任务信息"""
        return self.tasks.get(task_id)

    def stop_task(self, task_id: str) -> bool:
        """停止任务"""
        task = self.tasks.get(task_id)
        if not task:
            return False

        if task.status != "running":
            return False

        if task.process:
            try:
                task.process.kill()
                task.status = "stopped"
                task.end_time = time.time()
                return True
            except Exception:
                return False

        return False

    def list_tasks(self) -> list[BackgroundTask]:
        """列出所有任务"""
        return list(self.tasks.values())

    def cleanup_old_tasks(self, max_age_seconds: int = 3600):
        """清理旧任务（默认1小时）"""
        current_time = time.time()
        to_remove = []

        for task_id, task in self.tasks.items():
            if task.status in ("completed", "failed", "stopped"):
                if task.end_time and (current_time - task.end_time) > max_age_seconds:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self.tasks[task_id]


class RunCommandBackgroundTool(BaseTool):
    name = "run_command_background"
    description = (
        "在后台执行命令，不阻塞当前流程。"
        "适合长时间运行的任务（测试、构建等）。"
        "返回task_id，可用get_command_output查看输出。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "reason": {"type": "string", "description": "执行原因"},
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），默认300秒",
                "default": 300,
            },
        },
        "required": ["command"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        command = arguments["command"]
        reason = arguments.get("reason", "后台执行命令")
        timeout = int(arguments.get("timeout", 300))

        # 命令安全检查
        try:
            context.command_guard.validate_simple_command(command)
        except ValueError as exc:
            return ToolResult(ok=False, content="", error=f"命令无效: {exc}")

        from code_agent.schemas import CommandDecision

        decision = context.command_guard.decide(command)

        if decision == CommandDecision.DENY:
            return ToolResult(ok=False, content="", error=f"命令被策略拒绝: {command}")

        if decision == CommandDecision.REQUIRE_APPROVAL:
            parsed = context.command_guard.parse(command)
            if parsed.normalized not in getattr(context, "pre_approved_commands", set()):
                return ToolResult(
                    ok=False,
                    content="",
                    error=f"命令需要审批: {command}\n提示: 后台命令无法交互式审批，请先在前台执行一次获得批准",
                )

        # 启动后台任务
        manager = BackgroundCommandManager()
        task_id = manager.start_task(
            command=command,
            cwd=context.project_root,
            timeout=timeout,
            shell=False,
        )

        return ToolResult(
            ok=True,
            content=f"命令已在后台启动\n任务ID: {task_id}\n命令: {command}\n\n使用 get_command_output(task_id='{task_id}') 查看输出",
            metadata={"task_id": task_id, "command": command},
        )


class GetCommandOutputTool(BaseTool):
    name = "get_command_output"
    description = "获取后台命令的输出和状态。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "任务ID"},
        },
        "required": ["task_id"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        task_id = arguments["task_id"]
        manager = BackgroundCommandManager()
        task = manager.get_task(task_id)

        if not task:
            return ToolResult(ok=False, content="", error=f"任务不存在: {task_id}")

        # 计算运行时间
        if task.end_time:
            duration = task.end_time - task.start_time
        else:
            duration = time.time() - task.start_time

        # 构建输出
        lines = [
            f"任务ID: {task.task_id}",
            f"命令: {task.command}",
            f"状态: {task.status}",
            f"运行时间: {duration:.2f}秒",
        ]

        if task.exit_code is not None:
            lines.append(f"退出码: {task.exit_code}")

        if task.output:
            lines.append(f"\n标准输出:\n{task.output}")

        if task.error:
            lines.append(f"\n标准错误:\n{task.error}")

        content = "\n".join(lines)

        return ToolResult(
            ok=True,
            content=content,
            metadata={
                "task_id": task_id,
                "status": task.status,
                "exit_code": task.exit_code,
            },
        )


class StopCommandTool(BaseTool):
    name = "stop_command"
    description = "停止正在运行的后台命令。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "任务ID"},
        },
        "required": ["task_id"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        task_id = arguments["task_id"]
        manager = BackgroundCommandManager()

        if manager.stop_task(task_id):
            return ToolResult(ok=True, content=f"任务 {task_id} 已停止")
        else:
            return ToolResult(ok=False, content="", error=f"无法停止任务 {task_id}（可能已完成或不存在）")


class ListBackgroundCommandsTool(BaseTool):
    name = "list_background_commands"
    description = "列出所有后台命令及其状态。"
    parameters_schema = {"type": "object", "properties": {}}

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        manager = BackgroundCommandManager()
        tasks = manager.list_tasks()

        if not tasks:
            return ToolResult(ok=True, content="暂无后台任务")

        lines = ["后台任务列表:"]
        for task in sorted(tasks, key=lambda t: t.start_time, reverse=True):
            status_icon = {
                "running": "🔄",
                "completed": "✅",
                "failed": "❌",
                "stopped": "⏹️",
            }.get(task.status, "❓")

            duration = (
                (task.end_time or time.time()) - task.start_time
            )

            lines.append(
                f"  {status_icon} [{task.task_id}] {task.command[:50]}... "
                f"({task.status}, {duration:.1f}s)"
            )

        return ToolResult(ok=True, content="\n".join(lines))
