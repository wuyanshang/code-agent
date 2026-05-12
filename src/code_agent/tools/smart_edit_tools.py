from __future__ import annotations

import re
from typing import Any, Literal

from code_agent.schemas import ToolResult
from code_agent.services.diff_service import unified_diff
from code_agent.tools.base import BaseTool


def detect_indentation(content: str) -> tuple[Literal["tab", "space"], int]:
    """
    检测文件的缩进类型和级别。

    返回: (缩进类型, 缩进级别)
    - 缩进类型: "tab" 或 "space"
    - 缩进级别: tab为1，space为2/4/8等
    """
    lines = content.splitlines()

    # 统计tab和space缩进
    tab_count = 0
    space_indents: list[int] = []

    for line in lines:
        if not line or not line[0].isspace():
            continue

        # 检测是否使用tab
        if line.startswith('\t'):
            tab_count += 1
            continue

        # 检测space缩进级别
        spaces = len(line) - len(line.lstrip(' '))
        if spaces > 0:
            space_indents.append(spaces)

    # 判断使用tab还是space
    if tab_count > len(space_indents):
        return ("tab", 1)

    # 统计最常见的space缩进级别
    if not space_indents:
        return ("space", 4)  # 默认4空格

    # 找出最小的非零缩进（通常是基础缩进级别）
    min_indent = min(s for s in space_indents if s > 0)

    # 检查是否所有缩进都是min_indent的倍数
    if all(s % min_indent == 0 for s in space_indents):
        return ("space", min_indent)

    # 如果不是，返回最常见的缩进
    from collections import Counter
    common_indent = Counter(space_indents).most_common(1)[0][0]
    return ("space", common_indent)


def get_line_indent(line: str) -> str:
    """获取行的缩进部分"""
    return line[:len(line) - len(line.lstrip())]


def adjust_indent(text: str, target_indent: str) -> str:
    """
    调整文本块的缩进以匹配目标缩进。

    Args:
        text: 要调整的文本
        target_indent: 目标缩进字符串

    Returns:
        调整后的文本
    """
    lines = text.splitlines()
    if not lines:
        return text

    # 找出文本块的最小缩进
    min_indent_len = float('inf')
    for line in lines:
        if line.strip():  # 跳过空行
            indent = get_line_indent(line)
            min_indent_len = min(min_indent_len, len(indent))

    if min_indent_len == float('inf'):
        min_indent_len = 0

    # 移除最小缩进，然后添加目标缩进
    adjusted_lines = []
    for line in lines:
        if line.strip():
            # 移除原有的最小缩进
            relative_indent = line[int(min_indent_len):]
            # 计算相对缩进级别
            extra_indent = get_line_indent(relative_indent)
            # 添加目标缩进
            adjusted_lines.append(target_indent + extra_indent + relative_indent.lstrip())
        else:
            adjusted_lines.append(line)

    return '\n'.join(adjusted_lines)


class SmartReplaceTool(BaseTool):
    name = "smart_replace"
    description = (
        "智能替换文件内容，自动保持缩进对齐。"
        "支持正则表达式、多处替换、指定替换次数。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_text": {"type": "string", "description": "要替换的文本"},
            "new_text": {"type": "string", "description": "新文本"},
            "count": {
                "type": "integer",
                "description": "替换次数，-1表示全部替换",
                "default": 1,
            },
            "regex": {
                "type": "boolean",
                "description": "是否使用正则表达式",
                "default": False,
            },
            "preserve_indent": {
                "type": "boolean",
                "description": "是否保持缩进对齐",
                "default": True,
            },
        },
        "required": ["path", "old_text", "new_text"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        path = context.path_guard.ensure_allowed(arguments["path"])

        if not path.exists():
            return ToolResult(ok=False, content="", error=f"文件不存在: {path}")

        before = path.read_text(encoding="utf-8")
        old_text = arguments["old_text"]
        new_text = arguments["new_text"]
        count = int(arguments.get("count", 1))
        use_regex = bool(arguments.get("regex", False))
        preserve_indent = bool(arguments.get("preserve_indent", True))

        # 执行替换
        actual_count = 0
        if use_regex:
            try:
                if count == -1:
                    after = re.sub(old_text, new_text, before)
                    actual_count = len(re.findall(old_text, before))
                else:
                    after = re.sub(old_text, new_text, before, count=count)
                    actual_count = count
            except re.error as e:
                return ToolResult(ok=False, content="", error=f"正则表达式错误: {e}")
        else:
            # 字面量替换
            if old_text not in before:
                return ToolResult(ok=False, content="", error="未找到要替换的文本")

            if preserve_indent and '\n' in new_text:
                # 智能缩进替换
                after = self._replace_with_indent(before, old_text, new_text, count)
                actual_count = before.count(old_text) if count == -1 else min(count, before.count(old_text))
            else:
                # 普通替换
                if count == -1:
                    after = before.replace(old_text, new_text)
                    actual_count = before.count(old_text)
                else:
                    after = before.replace(old_text, new_text, count)
                    actual_count = min(count, before.count(old_text))

        # 写入文件
        path.write_text(after, encoding="utf-8")
        rel = str(path.relative_to(context.project_root))
        context.files_changed.add(rel)
        diff = unified_diff(before, after, rel)
        context.last_diff = diff

        count_msg = f"（替换了{actual_count}处）" if count == -1 or actual_count > 1 else ""
        return ToolResult(
            ok=True,
            content=f"已更新 {rel} {count_msg}",
            metadata={"diff": diff, "path": rel, "count": actual_count},
        )

    def _replace_with_indent(self, content: str, old_text: str, new_text: str, count: int) -> str:
        """替换时保持缩进对齐"""
        lines = content.splitlines(keepends=True)
        result_lines = []
        replacements_done = 0

        for line in lines:
            if old_text in line and (count == -1 or replacements_done < count):
                # 获取当前行的缩进
                indent = get_line_indent(line)
                # 调整新文本的缩进
                adjusted_new = adjust_indent(new_text, indent)
                # 执行替换
                new_line = line.replace(old_text, adjusted_new, 1)
                result_lines.append(new_line)
                replacements_done += 1
            else:
                result_lines.append(line)

        return ''.join(result_lines)


class InsertLinesTool(BaseTool):
    name = "insert_lines"
    description = "在文件的指定行号插入内容，自动检测并匹配缩进。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "line_number": {
                "type": "integer",
                "description": "插入位置的行号（1-based），在此行之前插入",
            },
            "content": {"type": "string", "description": "要插入的内容"},
            "match_indent": {
                "type": "boolean",
                "description": "是否自动匹配周围的缩进",
                "default": True,
            },
        },
        "required": ["path", "line_number", "content"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        path = context.path_guard.ensure_allowed(arguments["path"])

        if not path.exists():
            return ToolResult(ok=False, content="", error=f"文件不存在: {path}")

        before = path.read_text(encoding="utf-8")
        lines = before.splitlines(keepends=True)
        line_number = int(arguments["line_number"])
        content = arguments["content"]
        match_indent = bool(arguments.get("match_indent", True))

        if line_number < 1 or line_number > len(lines) + 1:
            return ToolResult(
                ok=False,
                content="",
                error=f"行号超出范围: {line_number} (文件共{len(lines)}行)",
            )

        # 自动匹配缩进
        if match_indent and line_number <= len(lines):
            # 使用目标行的缩进
            target_line = lines[line_number - 1]
            target_indent = get_line_indent(target_line)
            content = adjust_indent(content, target_indent)

        # 确保内容以换行符结尾
        if not content.endswith('\n'):
            content += '\n'

        # 插入内容
        insert_pos = line_number - 1
        lines.insert(insert_pos, content)
        after = ''.join(lines)

        # 写入文件
        path.write_text(after, encoding="utf-8")
        rel = str(path.relative_to(context.project_root))
        context.files_changed.add(rel)
        diff = unified_diff(before, after, rel)
        context.last_diff = diff

        return ToolResult(
            ok=True,
            content=f"已在 {rel} 第{line_number}行插入内容",
            metadata={"diff": diff, "path": rel},
        )


class DeleteLinesTool(BaseTool):
    name = "delete_lines"
    description = "删除文件中指定范围的行。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "start_line": {"type": "integer", "description": "起始行号（1-based，包含）"},
            "end_line": {
                "type": "integer",
                "description": "结束行号（1-based，包含），不指定则只删除start_line",
            },
        },
        "required": ["path", "start_line"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        path = context.path_guard.ensure_allowed(arguments["path"])

        if not path.exists():
            return ToolResult(ok=False, content="", error=f"文件不存在: {path}")

        before = path.read_text(encoding="utf-8")
        lines = before.splitlines(keepends=True)
        start_line = int(arguments["start_line"])
        end_line = int(arguments.get("end_line", start_line))

        if start_line < 1 or start_line > len(lines):
            return ToolResult(
                ok=False,
                content="",
                error=f"起始行号超出范围: {start_line} (文件共{len(lines)}行)",
            )

        if end_line < start_line or end_line > len(lines):
            return ToolResult(
                ok=False,
                content="",
                error=f"结束行号无效: {end_line}",
            )

        # 删除指定行（转换为0-based索引）
        del lines[start_line - 1 : end_line]
        after = ''.join(lines)

        # 写入文件
        path.write_text(after, encoding="utf-8")
        rel = str(path.relative_to(context.project_root))
        context.files_changed.add(rel)
        diff = unified_diff(before, after, rel)
        context.last_diff = diff

        line_range = f"{start_line}-{end_line}" if end_line > start_line else str(start_line)
        return ToolResult(
            ok=True,
            content=f"已删除 {rel} 第{line_range}行",
            metadata={"diff": diff, "path": rel},
        )
