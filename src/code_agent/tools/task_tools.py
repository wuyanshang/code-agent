from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: Literal["pending", "in_progress", "completed"] = "pending"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    active_form: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)


class TaskManager:
    """任务管理器，负责任务的创建、更新和查询。"""

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.tasks: dict[str, Task] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载任务列表。"""
        if not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            for task_data in data.get("tasks", []):
                task = Task(**task_data)
                self.tasks[task.id] = task
        except Exception:
            pass

    def _save(self) -> None:
        """保存任务列表到文件。"""
        data = {"tasks": [asdict(task) for task in self.tasks.values()]}
        self.storage_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _generate_id(self) -> str:
        """生成新的任务ID。"""
        existing_ids = {int(tid) for tid in self.tasks.keys() if tid.isdigit()}
        next_id = max(existing_ids, default=0) + 1
        return str(next_id)

    def create_task(
        self,
        subject: str,
        description: str,
        active_form: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """创建新任务。"""
        task_id = self._generate_id()
        task = Task(
            id=task_id,
            subject=subject,
            description=description,
            active_form=active_form,
            metadata=metadata or {},
        )
        self.tasks[task_id] = task
        self._save()
        return task

    def update_task(
        self,
        task_id: str,
        status: Literal["pending", "in_progress", "completed"] | None = None,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        metadata: dict[str, Any] | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> Task:
        """更新任务。"""
        if task_id not in self.tasks:
            raise KeyError(f"Task {task_id} not found")

        task = self.tasks[task_id]
        if status is not None:
            task.status = status
        if subject is not None:
            task.subject = subject
        if description is not None:
            task.description = description
        if active_form is not None:
            task.active_form = active_form
        if metadata is not None:
            task.metadata.update(metadata)
        if add_blocks:
            task.blocks.extend(b for b in add_blocks if b not in task.blocks)
        if add_blocked_by:
            task.blocked_by.extend(b for b in add_blocked_by if b not in task.blocked_by)

        task.updated_at = datetime.now().isoformat()
        self._save()
        return task

    def get_task(self, task_id: str) -> Task:
        """获取任务详情。"""
        if task_id not in self.tasks:
            raise KeyError(f"Task {task_id} not found")
        return self.tasks[task_id]

    def list_tasks(self) -> list[Task]:
        """列出所有任务。"""
        return sorted(self.tasks.values(), key=lambda t: int(t.id) if t.id.isdigit() else 0)


class TaskCreateTool(BaseTool):
    name = "task_create"
    description = "创建一个新任务，用于跟踪复杂工作的进度。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "任务标题（简短描述）"},
            "description": {"type": "string", "description": "任务详细描述"},
            "activeForm": {"type": "string", "description": "进行中时显示的动词形式（如'正在修复bug'）"},
            "metadata": {"type": "object", "description": "任务元数据"},
        },
        "required": ["subject", "description"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        manager = self._get_manager(context)
        task = manager.create_task(
            subject=arguments["subject"],
            description=arguments["description"],
            active_form=arguments.get("activeForm"),
            metadata=arguments.get("metadata"),
        )
        return ToolResult(
            ok=True,
            content=f"任务 #{task.id} 已创建: {task.subject}",
            metadata={"task_id": task.id},
        )

    def _get_manager(self, context: Any) -> TaskManager:
        if not hasattr(context, "_task_manager"):
            storage_path = context.project_root / ".code-agent" / "tasks.json"
            context._task_manager = TaskManager(storage_path)
        return context._task_manager


class TaskUpdateTool(BaseTool):
    name = "task_update"
    description = "更新任务状态或内容。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "taskId": {"type": "string", "description": "任务ID"},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "任务状态",
            },
            "subject": {"type": "string", "description": "新的任务标题"},
            "description": {"type": "string", "description": "新的任务描述"},
            "activeForm": {"type": "string", "description": "进行中时显示的动词形式"},
            "metadata": {"type": "object", "description": "要合并的元数据"},
            "addBlocks": {"type": "array", "items": {"type": "string"}, "description": "添加阻塞的任务ID"},
            "addBlockedBy": {"type": "array", "items": {"type": "string"}, "description": "添加被阻塞的任务ID"},
        },
        "required": ["taskId"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        manager = self._get_manager(context)
        try:
            task = manager.update_task(
                task_id=arguments["taskId"],
                status=arguments.get("status"),
                subject=arguments.get("subject"),
                description=arguments.get("description"),
                active_form=arguments.get("activeForm"),
                metadata=arguments.get("metadata"),
                add_blocks=arguments.get("addBlocks"),
                add_blocked_by=arguments.get("addBlockedBy"),
            )
            return ToolResult(
                ok=True,
                content=f"任务 #{task.id} 已更新: {task.subject} [{task.status}]",
            )
        except KeyError as e:
            return ToolResult(ok=False, content="", error=str(e))

    def _get_manager(self, context: Any) -> TaskManager:
        if not hasattr(context, "_task_manager"):
            storage_path = context.project_root / ".code-agent" / "tasks.json"
            context._task_manager = TaskManager(storage_path)
        return context._task_manager


class TaskListTool(BaseTool):
    name = "task_list"
    description = "列出所有任务及其状态。"
    parameters_schema = {"type": "object", "properties": {}}

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        manager = self._get_manager(context)
        tasks = manager.list_tasks()
        if not tasks:
            return ToolResult(ok=True, content="暂无任务")

        lines = ["任务列表:"]
        for task in tasks:
            status_icon = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}[task.status]
            blocked_info = f" [被阻塞: {', '.join(task.blocked_by)}]" if task.blocked_by else ""
            lines.append(f"  #{task.id} {status_icon} {task.subject} [{task.status}]{blocked_info}")

        return ToolResult(ok=True, content="\n".join(lines))

    def _get_manager(self, context: Any) -> TaskManager:
        if not hasattr(context, "_task_manager"):
            storage_path = context.project_root / ".code-agent" / "tasks.json"
            context._task_manager = TaskManager(storage_path)
        return context._task_manager


class TaskGetTool(BaseTool):
    name = "task_get"
    description = "获取任务的详细信息。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "taskId": {"type": "string", "description": "任务ID"},
        },
        "required": ["taskId"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        manager = self._get_manager(context)
        try:
            task = manager.get_task(arguments["taskId"])
            info = [
                f"任务 #{task.id}: {task.subject}",
                f"状态: {task.status}",
                f"描述: {task.description}",
                f"创建时间: {task.created_at}",
                f"更新时间: {task.updated_at}",
            ]
            if task.active_form:
                info.append(f"进行中形式: {task.active_form}")
            if task.blocks:
                info.append(f"阻塞任务: {', '.join(task.blocks)}")
            if task.blocked_by:
                info.append(f"被阻塞: {', '.join(task.blocked_by)}")
            if task.metadata:
                info.append(f"元数据: {json.dumps(task.metadata, ensure_ascii=False)}")

            return ToolResult(ok=True, content="\n".join(info))
        except KeyError as e:
            return ToolResult(ok=False, content="", error=str(e))

    def _get_manager(self, context: Any) -> TaskManager:
        if not hasattr(context, "_task_manager"):
            storage_path = context.project_root / ".code-agent" / "tasks.json"
            context._task_manager = TaskManager(storage_path)
        return context._task_manager

