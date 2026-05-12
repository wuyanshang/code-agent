"""
Diff 可视化工具 - 查看会话中的所有文件变更
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from code_agent.schemas import ToolResult
from code_agent.services.diff_service import unified_diff
from code_agent.tools.base import BaseTool


class ViewSessionDiffTool(BaseTool):
    """查看本次会话的所有文件变更"""

    name = "view_session_diff"
    description = (
        "查看本次会话中所有文件的变更摘要。"
        "显示修改、新增、删除的文件列表及统计信息。"
        "用于在 commit 前 review 所有改动。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "filter_type": {
                "type": "string",
                "enum": ["all", "modified", "new", "deleted"],
                "description": "筛选类型：all=所有，modified=修改的，new=新增的，deleted=删除的",
                "default": "all",
            },
            "show_stats": {
                "type": "boolean",
                "description": "是否显示统计信息（增删行数）",
                "default": True,
            },
        },
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        filter_type = arguments.get("filter_type", "all")
        show_stats = arguments.get("show_stats", True)

        if not context.files_changed:
            return ToolResult(ok=True, content="本次会话未修改任何文件")

        # 分类文件
        modified_files = []
        new_files = []
        deleted_files = []

        for rel_path in sorted(context.files_changed):
            full_path = context.project_root / rel_path

            # 检查文件历史
            if hasattr(context, "file_history") and context.file_history:
                # 通过文件历史判断是新增还是修改
                if rel_path in context.file_history.state.tracked_files:
                    # 查找第一个备份
                    first_backup = None
                    for snapshot in context.file_history.state.snapshots:
                        if rel_path in snapshot.tracked_files:
                            first_backup = snapshot.tracked_files[rel_path]
                            break

                    if first_backup and first_backup.backup_path is None:
                        # 原本不存在，是新增文件
                        if full_path.exists():
                            new_files.append(rel_path)
                        else:
                            deleted_files.append(rel_path)
                    else:
                        # 原本存在，是修改
                        if full_path.exists():
                            modified_files.append(rel_path)
                        else:
                            deleted_files.append(rel_path)
                else:
                    # 没有历史记录，判断当前状态
                    if full_path.exists():
                        new_files.append(rel_path)
                    else:
                        deleted_files.append(rel_path)
            else:
                # 没有文件历史，简单判断
                if full_path.exists():
                    modified_files.append(rel_path)

        # 应用筛选
        if filter_type == "modified":
            files_to_show = modified_files
        elif filter_type == "new":
            files_to_show = new_files
        elif filter_type == "deleted":
            files_to_show = deleted_files
        else:
            files_to_show = modified_files + new_files + deleted_files

        if not files_to_show:
            return ToolResult(ok=True, content=f"没有 {filter_type} 类型的文件")

        # 构建输出
        lines = ["╭─── 会话变更摘要 ───╮"]
        lines.append(f"│ 修改: {len(modified_files)} 个文件")
        lines.append(f"│ 新增: {len(new_files)} 个文件")
        lines.append(f"│ 删除: {len(deleted_files)} 个文件")
        lines.append("╰" + "─" * 20 + "╯")
        lines.append("")

        # 显示文件列表
        for rel_path in files_to_show:
            full_path = context.project_root / rel_path

            # 判断文件类型
            if rel_path in new_files:
                file_type = "新增"
            elif rel_path in deleted_files:
                file_type = "删除"
            else:
                file_type = "修改"

            # 计算统计信息
            if show_stats and full_path.exists():
                stats = self._calculate_stats(context, rel_path, full_path)
                lines.append(f"{rel_path:50} {file_type:4} {stats}")
            else:
                lines.append(f"{rel_path:50} {file_type:4}")

        return ToolResult(ok=True, content="\n".join(lines))

    def _calculate_stats(self, context: Any, rel_path: str, full_path: Path) -> str:
        """计算文件的增删行数"""
        try:
            current_content = full_path.read_text(encoding="utf-8")

            # 尝试从文件历史获取原始内容
            original_content = ""
            if hasattr(context, "file_history") and context.file_history:
                for snapshot in context.file_history.state.snapshots:
                    if rel_path in snapshot.tracked_files:
                        backup = snapshot.tracked_files[rel_path]
                        if backup.backup_path and backup.backup_path.exists():
                            original_content = backup.backup_path.read_text(encoding="utf-8")
                        break

            # 计算差异
            original_lines = original_content.splitlines()
            current_lines = current_content.splitlines()

            added = len(current_lines) - len(original_lines)
            if added > 0:
                return f"+{added:3} 行"
            elif added < 0:
                return f"{added:4} 行"
            else:
                return "  0 行"
        except (OSError, UnicodeDecodeError):
            return "  ? 行"


class ViewFileDiffTool(BaseTool):
    """查看单个文件的详细 diff"""

    name = "view_file_diff"
    description = (
        "查看指定文件的详细 diff（unified diff 格式）。"
        "显示具体的代码变更，包括上下文。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（相对项目根）",
            },
            "context_lines": {
                "type": "integer",
                "description": "上下文行数（默认 3）",
                "default": 3,
            },
        },
        "required": ["path"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        rel_path = arguments["path"]
        context_lines = arguments.get("context_lines", 3)

        # 检查文件是否在变更列表中
        if rel_path not in context.files_changed:
            return ToolResult(
                ok=False,
                content="",
                error=f"文件 {rel_path} 未在本次会话中修改"
            )

        full_path = context.project_root / rel_path

        # 获取当前内容
        if full_path.exists():
            current_content = full_path.read_text(encoding="utf-8")
        else:
            current_content = ""

        # 获取原始内容
        original_content = ""
        if hasattr(context, "file_history") and context.file_history:
            for snapshot in context.file_history.state.snapshots:
                if rel_path in snapshot.tracked_files:
                    backup = snapshot.tracked_files[rel_path]
                    if backup.backup_path and backup.backup_path.exists():
                        original_content = backup.backup_path.read_text(encoding="utf-8")
                    break

        # 生成 diff
        diff = unified_diff(original_content, current_content, rel_path)

        if not diff:
            return ToolResult(ok=True, content=f"{rel_path}: 无变更")

        return ToolResult(ok=True, content=diff)


class CompareFileVersionsTool(BaseTool):
    """比较文件的不同版本"""

    name = "compare_file_versions"
    description = (
        "比较文件在会话中的不同版本。"
        "可以查看文件在不同时间点的内容差异。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（相对项目根）",
            },
            "version": {
                "type": "string",
                "enum": ["original", "current"],
                "description": "要查看的版本：original=原始版本，current=当前版本",
                "default": "current",
            },
        },
        "required": ["path"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        rel_path = arguments["path"]
        version = arguments.get("version", "current")

        full_path = context.project_root / rel_path

        if version == "current":
            # 返回当前内容
            if not full_path.exists():
                return ToolResult(ok=False, content="", error=f"文件 {rel_path} 不存在")

            try:
                content = full_path.read_text(encoding="utf-8")
                lines = content.splitlines()
                # 添加行号
                numbered_lines = [f"{i+1:4} | {line}" for i, line in enumerate(lines)]
                return ToolResult(
                    ok=True,
                    content=f"=== {rel_path} (当前版本) ===\n" + "\n".join(numbered_lines)
                )
            except (OSError, UnicodeDecodeError) as e:
                return ToolResult(ok=False, content="", error=f"读取文件失败: {e}")

        else:  # original
            # 返回原始内容
            if not hasattr(context, "file_history") or not context.file_history:
                return ToolResult(ok=False, content="", error="没有文件历史记录")

            for snapshot in context.file_history.state.snapshots:
                if rel_path in snapshot.tracked_files:
                    backup = snapshot.tracked_files[rel_path]

                    if backup.backup_path is None:
                        return ToolResult(
                            ok=True,
                            content=f"=== {rel_path} (原始版本) ===\n(文件原本不存在)"
                        )

                    if not backup.backup_path.exists():
                        return ToolResult(
                            ok=False,
                            content="",
                            error="备份文件不存在"
                        )

                    try:
                        content = backup.backup_path.read_text(encoding="utf-8")
                        lines = content.splitlines()
                        numbered_lines = [f"{i+1:4} | {line}" for i, line in enumerate(lines)]
                        return ToolResult(
                            ok=True,
                            content=f"=== {rel_path} (原始版本) ===\n" + "\n".join(numbered_lines)
                        )
                    except (OSError, UnicodeDecodeError) as e:
                        return ToolResult(ok=False, content="", error=f"读取备份失败: {e}")

            return ToolResult(ok=False, content="", error=f"未找到文件 {rel_path} 的历史记录")
