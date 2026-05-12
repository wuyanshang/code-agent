import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from code_agent.tools.task_tools import (
    Task,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskManager,
    TaskUpdateTool,
)


class MockContext:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root


def test_task_manager_create_and_list() -> None:
    with TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "tasks.json"
        manager = TaskManager(storage_path)

        task1 = manager.create_task("修复登录bug", "用户无法登录系统")
        assert task1.id == "1"
        assert task1.subject == "修复登录bug"
        assert task1.status == "pending"

        task2 = manager.create_task("添加日志功能", "在关键位置添加日志")
        assert task2.id == "2"

        tasks = manager.list_tasks()
        assert len(tasks) == 2
        assert tasks[0].id == "1"
        assert tasks[1].id == "2"


def test_task_manager_update() -> None:
    with TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "tasks.json"
        manager = TaskManager(storage_path)

        task = manager.create_task("测试任务", "这是一个测试")
        assert task.status == "pending"

        updated = manager.update_task(task.id, status="in_progress")
        assert updated.status == "in_progress"

        updated = manager.update_task(task.id, status="completed")
        assert updated.status == "completed"


def test_task_manager_persistence() -> None:
    with TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "tasks.json"

        # 创建任务并保存
        manager1 = TaskManager(storage_path)
        manager1.create_task("任务1", "描述1")
        manager1.create_task("任务2", "描述2")

        # 重新加载
        manager2 = TaskManager(storage_path)
        tasks = manager2.list_tasks()
        assert len(tasks) == 2
        assert tasks[0].subject == "任务1"
        assert tasks[1].subject == "任务2"


def test_task_create_tool() -> None:
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        tool = TaskCreateTool()

        result = tool.execute(
            {"subject": "实现功能X", "description": "添加新功能X到系统"},
            context,
        )

        assert result.ok
        assert "任务 #1 已创建" in result.content
        assert result.metadata["task_id"] == "1"


def test_task_update_tool() -> None:
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        create_tool = TaskCreateTool()
        update_tool = TaskUpdateTool()

        # 创建任务
        create_tool.execute(
            {"subject": "任务A", "description": "描述A"},
            context,
        )

        # 更新任务
        result = update_tool.execute(
            {"taskId": "1", "status": "in_progress"},
            context,
        )

        assert result.ok
        assert "已更新" in result.content
        assert "[in_progress]" in result.content


def test_task_list_tool() -> None:
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        create_tool = TaskCreateTool()
        list_tool = TaskListTool()

        # 创建多个任务
        create_tool.execute({"subject": "任务1", "description": "描述1"}, context)
        create_tool.execute({"subject": "任务2", "description": "描述2"}, context)

        # 列出任务
        result = list_tool.execute({}, context)

        assert result.ok
        assert "任务1" in result.content
        assert "任务2" in result.content
        assert "⏳" in result.content  # pending状态图标


def test_task_get_tool() -> None:
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        create_tool = TaskCreateTool()
        get_tool = TaskGetTool()

        # 创建任务
        create_tool.execute(
            {"subject": "详细任务", "description": "这是详细描述", "activeForm": "正在处理"},
            context,
        )

        # 获取任务详情
        result = get_tool.execute({"taskId": "1"}, context)

        assert result.ok
        assert "详细任务" in result.content
        assert "这是详细描述" in result.content
        assert "正在处理" in result.content


def test_task_blocking() -> None:
    with TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "tasks.json"
        manager = TaskManager(storage_path)

        task1 = manager.create_task("基础任务", "必须先完成")
        task2 = manager.create_task("依赖任务", "依赖task1")

        # 设置阻塞关系
        manager.update_task(task2.id, add_blocked_by=[task1.id])
        manager.update_task(task1.id, add_blocks=[task2.id])

        task2_updated = manager.get_task(task2.id)
        assert task1.id in task2_updated.blocked_by

        task1_updated = manager.get_task(task1.id)
        assert task2.id in task1_updated.blocks
