import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from code_agent.tools.background_command_tools import (
    BackgroundCommandManager,
    GetCommandOutputTool,
    ListBackgroundCommandsTool,
    RunCommandBackgroundTool,
    StopCommandTool,
)


class MockContext:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.pre_approved_commands = set()

    class CommandGuard:
        def validate_simple_command(self, command: str):
            if not command.strip():
                raise ValueError("command is empty")

        def decide(self, command: str):
            from code_agent.schemas import CommandDecision
            # 简单命令允许
            if command.startswith(("echo", "dir", "ls")):
                return CommandDecision.ALLOW
            return CommandDecision.REQUIRE_APPROVAL

        def parse(self, command: str):
            class ParsedCommand:
                normalized = command.lower()
            return ParsedCommand()

    @property
    def command_guard(self):
        return self.CommandGuard()


def test_background_command_manager_singleton():
    """测试单例模式"""
    manager1 = BackgroundCommandManager()
    manager2 = BackgroundCommandManager()
    assert manager1 is manager2


def test_run_simple_command():
    """测试运行简单命令"""
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        tool = RunCommandBackgroundTool()

        result = tool.execute(
            {"command": "echo hello"},
            context,
        )

        assert result.ok
        assert "task_id" in result.metadata
        task_id = result.metadata["task_id"]

        # 等待命令完成
        time.sleep(0.5)

        # 获取输出
        get_tool = GetCommandOutputTool()
        output_result = get_tool.execute({"task_id": task_id}, context)

        assert output_result.ok
        assert "hello" in output_result.content.lower()
        assert "completed" in output_result.content


def test_command_timeout():
    """测试命令超时"""
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        tool = RunCommandBackgroundTool()

        # Windows: timeout命令，Linux: sleep命令
        import platform
        if platform.system() == "Windows":
            cmd = "timeout /t 10"
            context.pre_approved_commands.add("timeout /t 10")
        else:
            cmd = "sleep 10"
            context.pre_approved_commands.add("sleep 10")

        result = tool.execute(
            {"command": cmd, "timeout": 1},
            context,
        )

        assert result.ok
        task_id = result.metadata["task_id"]

        # 等待超时
        time.sleep(2)

        # 检查状态
        get_tool = GetCommandOutputTool()
        output_result = get_tool.execute({"task_id": task_id}, context)

        assert output_result.ok
        assert "failed" in output_result.content.lower()


def test_stop_command():
    """测试停止命令"""
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        run_tool = RunCommandBackgroundTool()

        # 启动长时间命令
        import platform
        if platform.system() == "Windows":
            cmd = "timeout /t 30"
            context.pre_approved_commands.add("timeout /t 30")
        else:
            cmd = "sleep 30"
            context.pre_approved_commands.add("sleep 30")

        result = run_tool.execute({"command": cmd}, context)
        assert result.ok
        task_id = result.metadata["task_id"]

        # 等待命令启动
        time.sleep(0.2)

        # 停止命令
        stop_tool = StopCommandTool()
        stop_result = stop_tool.execute({"task_id": task_id}, context)

        # 可能已经完成或成功停止
        # 只要不是运行中就算成功
        get_tool = GetCommandOutputTool()
        output_result = get_tool.execute({"task_id": task_id}, context)
        assert output_result.ok
        # 状态应该不是running
        assert "running" not in output_result.metadata.get("status", "")


def test_list_background_commands():
    """测试列出后台命令"""
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        run_tool = RunCommandBackgroundTool()
        list_tool = ListBackgroundCommandsTool()

        # 启动几个命令
        run_tool.execute({"command": "echo test1"}, context)
        run_tool.execute({"command": "echo test2"}, context)

        time.sleep(0.5)

        # 列出命令
        result = list_tool.execute({}, context)

        assert result.ok
        assert "test1" in result.content or "test2" in result.content


def test_get_nonexistent_task():
    """测试获取不存在的任务"""
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        tool = GetCommandOutputTool()

        result = tool.execute({"task_id": "nonexistent"}, context)

        assert not result.ok
        assert "不存在" in result.error


def test_command_approval_required():
    """测试需要审批的命令"""
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        tool = RunCommandBackgroundTool()

        # 未审批的命令
        result = tool.execute({"command": "python test.py"}, context)

        assert not result.ok
        assert "审批" in result.error

        # 预先批准
        context.pre_approved_commands.add("python test.py")
        result = tool.execute({"command": "python test.py"}, context)

        # 这次应该成功（虽然文件不存在会失败，但至少通过了审批）
        assert result.ok


def test_manager_cleanup():
    """测试清理旧任务"""
    manager = BackgroundCommandManager()

    # 创建一个已完成的旧任务
    task_id = manager.start_task(
        command="echo test",
        cwd=Path("."),
        timeout=10,
        shell=False,
    )

    time.sleep(0.5)

    # 手动设置为很久以前完成
    task = manager.get_task(task_id)
    if task:
        task.end_time = time.time() - 7200  # 2小时前

    # 清理
    manager.cleanup_old_tasks(max_age_seconds=3600)

    # 任务应该被清理
    assert manager.get_task(task_id) is None
