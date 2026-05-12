from __future__ import annotations

from typing import Any

from code_agent.schemas import ToolResult
from code_agent.services.diff_service import unified_diff
from code_agent.tools.base import BaseTool
from code_agent.tools.file_tools import _read_text_auto


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "写入整个文件内容。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        path = context.path_guard.ensure_allowed(arguments["path"])
        rel = str(path.relative_to(context.project_root))

        # 在修改前备份文件
        if hasattr(context, "file_history") and context.file_history:
            context.file_history.track_file_edit(path, rel, len(context.session.messages))

        before = _read_text_auto(path) if path.exists() else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments["content"], encoding="utf-8")
        context.files_changed.add(rel)
        diff = unified_diff(before, arguments["content"], rel)
        context.last_diff = diff
        return ToolResult(ok=True, content=f"wrote {rel}", metadata={"diff": diff, "path": rel})


class ReplaceInFileTool(BaseTool):
    name = "replace_in_file"
    description = "在文件中进行一次精确替换。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        path = context.path_guard.ensure_allowed(arguments["path"])
        rel = str(path.relative_to(context.project_root))

        # 在修改前备份文件
        if hasattr(context, "file_history") and context.file_history:
            context.file_history.track_file_edit(path, rel, len(context.session.messages))

        before = _read_text_auto(path)
        old_text = arguments["old_text"]
        if old_text not in before:
            return ToolResult(ok=False, content="", error="old_text not found")
        after = before.replace(old_text, arguments["new_text"], 1)
        path.write_text(after, encoding="utf-8")
        context.files_changed.add(rel)
        diff = unified_diff(before, after, rel)
        context.last_diff = diff
        return ToolResult(ok=True, content=f"updated {rel}", metadata={"diff": diff, "path": rel})


class AppendFileTool(BaseTool):
    name = "append_file"
    description = "向文件末尾追加内容。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        path = context.path_guard.ensure_allowed(arguments["path"])
        rel = str(path.relative_to(context.project_root))

        # 在修改前备份文件
        if hasattr(context, "file_history") and context.file_history:
            context.file_history.track_file_edit(path, rel, len(context.session.messages))

        before = _read_text_auto(path) if path.exists() else ""
        after = before + arguments["content"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
        context.files_changed.add(rel)
        diff = unified_diff(before, after, rel)
        context.last_diff = diff
        return ToolResult(ok=True, content=f"appended to {rel}", metadata={"diff": diff, "path": rel})


class PreviewDiffTool(BaseTool):
    name = "preview_diff"
    description = "查看最近一次文件修改的 diff。"
    parameters_schema = {"type": "object", "properties": {}}

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        diff = context.last_diff or ""
        return ToolResult(ok=True, content=diff or "no diff available")
