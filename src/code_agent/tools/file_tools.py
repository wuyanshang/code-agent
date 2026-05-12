from __future__ import annotations

import locale
from pathlib import Path
from typing import Any

from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool

_FALLBACK_ENCODINGS = ["utf-8-sig", "utf-8", "gbk", "latin-1"]


def _read_text_auto(path: Path) -> str:
    """自动检测编码读取文件，依次尝试系统编码、UTF-8、GBK，兜底 latin-1。"""
    system_enc = locale.getpreferredencoding(False)
    candidates = [system_enc] + [e for e in _FALLBACK_ENCODINGS if e.lower() != system_enc.lower()]
    for enc in candidates:
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_bytes().decode("latin-1")


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "列出指定目录下的文件和子目录。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_depth": {"type": "integer", "default": 2},
        },
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        target = context.path_guard.ensure_allowed(arguments.get("path", "."))
        max_depth = int(arguments.get("max_depth", 2))
        lines: list[str] = []
        base_depth = len(target.parts)
        for path in sorted(target.rglob("*")):
            depth = len(path.parts) - base_depth
            if depth > max_depth:
                continue
            lines.append(str(path.relative_to(context.project_root)))
        return ToolResult(ok=True, content="\n".join(lines[:200]))


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "读取文本文件，可指定起止行。"
        "大文件（>256KB）会报错，请使用 start_line 和 end_line 分段读取。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "default": 1},
            "end_line": {"type": "integer"},
        },
        "required": ["path"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        path = context.path_guard.ensure_allowed(arguments["path"])

        # 检查文件大小（读取前）
        if path.exists():
            file_size = path.stat().st_size
            max_size = context.config.tools.read_file_max_size_bytes

            if file_size > max_size:
                size_mb = file_size / (1024 * 1024)
                limit_kb = max_size / 1024
                return ToolResult(
                    ok=False,
                    content="",
                    error=(
                        f"文件过大 ({size_mb:.2f}MB > {limit_kb:.0f}KB)。"
                        f"请使用 start_line 和 end_line 参数分段读取。"
                        f"例如：先读取前100行查看结构，再决定读取哪些部分。"
                    )
                )

        start_line = max(int(arguments.get("start_line", 1)), 1)
        end_line = arguments.get("end_line")
        text = _read_text_auto(path)
        lines = text.splitlines()
        selected = lines[start_line - 1 : end_line]
        content = "\n".join(selected)

        # 检查输出大小（读取后）
        if len(content) > context.config.tools.read_file_max_chars:
            chars_k = len(content) / 1000
            limit_k = context.config.tools.read_file_max_chars / 1000
            return ToolResult(
                ok=False,
                content="",
                error=(
                    f"输出过大 ({chars_k:.1f}K字符 > {limit_k:.1f}K字符)。"
                    f"请缩小读取范围（当前 {start_line}-{end_line or len(lines)} 行）。"
                )
            )

        return ToolResult(ok=True, content=content)


class FindFilesTool(BaseTool):
    name = "find_files"
    description = "按文件名关键词查找文件。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
        },
        "required": ["pattern"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        pattern = arguments["pattern"].lower()
        matches: list[str] = []
        ignored = set(context.config.project.ignore_patterns)
        for path in context.project_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(context.project_root)
            if ignored.intersection(rel.parts):
                continue
            if pattern in path.name.lower():
                matches.append(str(rel))
        return ToolResult(ok=True, content="\n".join(matches[:200]))


class GlobFilesTool(BaseTool):
    name = "glob_files"
    description = (
        "按 glob 模式列出项目内文件路径（相对项目根）。"
        "适合批量定位源码：如 **/*.py、src/**/*.ts、**/test_*.py。"
        "path 为起始目录（默认项目根下 .）。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "glob，如 **/*.py、*.md",
            },
            "path": {
                "type": "string",
                "description": "起始目录（相对项目根），默认 .",
                "default": ".",
            },
        },
        "required": ["pattern"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        pattern = (arguments.get("pattern") or "").strip()
        if not pattern:
            return ToolResult(ok=False, content="", error="pattern 不能为空")
        rel_base = (arguments.get("path") or ".").strip() or "."
        try:
            base: Path = context.path_guard.ensure_allowed(rel_base)
        except ValueError as exc:
            return ToolResult(ok=False, content="", error=str(exc))
        if not base.is_dir():
            return ToolResult(ok=False, content="", error=f"不是目录: {rel_base}")

        try:
            raw_matches = sorted(base.glob(pattern))
        except Exception as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        ignored = set(context.config.project.ignore_patterns)
        out: list[str] = []
        for path in raw_matches:
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(context.project_root)
            except ValueError:
                continue
            if ignored.intersection(rel.parts):
                continue
            out.append(str(rel))
            if len(out) >= 200:
                break
        return ToolResult(ok=True, content="\n".join(out))