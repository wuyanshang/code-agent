from __future__ import annotations

import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool

# rg --type 常见类型与后缀（Python 回退用，非完整 type-list）
_TYPE_SUFFIXES: dict[str, frozenset[str]] = {
    "py": frozenset({".py", ".pyi"}),
    "js": frozenset({".js", ".jsx", ".mjs", ".cjs"}),
    "ts": frozenset({".ts", ".tsx"}),
    "rust": frozenset({".rs"}),
    "go": frozenset({".go"}),
    "java": frozenset({".java"}),
    "ruby": frozenset({".rb"}),
    "php": frozenset({".php"}),
    "c": frozenset({".c", ".h"}),
    "cpp": frozenset({".cpp", ".cc", ".cxx", ".hpp", ".hh"}),
    "cs": frozenset({".cs"}),
    "swift": frozenset({".swift"}),
    "kotlin": frozenset({".kt", ".kts"}),
    "md": frozenset({".md", ".markdown"}),
    "json": frozenset({".json"}),
    "yaml": frozenset({".yaml", ".yml"}),
    "toml": frozenset({".toml"}),
    "html": frozenset({".html", ".htm"}),
    "css": frozenset({".css"}),
    "sh": frozenset({".sh", ".bash"}),
}


class SearchTextTool(BaseTool):
    name = "search_text"
    description = (
        "在项目中搜索文本（默认纯 Python；可选 ripgrep/rg）。"
        "默认 output_mode=files_with_matches（先列路径，省上下文）；要看匹配行请设 content；count=每文件命中行数。"
        "支持 glob、ignore_case、type（如 py）、context/context_before/context_after、"
        "head_limit（0=不限制，缺省用配置 search_default_head_limit，默认 250）、offset；"
        "fixed_string 为 true 时用字面量。"
        "默认 tools.search_use_ripgrep=false（纯 Python）；设为 true 时优先 rg，未安装则回退 Python。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索模式；非 fixed_string 时为正则"},
            "path": {"type": "string", "description": "搜索根目录（相对项目根），默认全项目"},
            "glob": {"type": "string", "description": "rg --glob，如 *.py"},
            "fixed_string": {
                "type": "boolean",
                "description": "为 true 时 rg -F 字面量",
                "default": False,
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "files_with_matches=路径列表（默认）；content=匹配行；count=每文件计数",
                "default": "files_with_matches",
            },
            "ignore_case": {
                "type": "boolean",
                "description": "rg -i",
                "default": False,
            },
            "type": {
                "type": "string",
                "description": "rg --type，如 py、ts、rust",
            },
            "line_numbers": {
                "type": "boolean",
                "description": "content 模式是否带行号（rg -n），默认 true",
                "default": True,
            },
            "context": {
                "type": "integer",
                "description": "content 模式：匹配行上下各 N 行（rg -C）",
            },
            "context_before": {
                "type": "integer",
                "description": "content 模式：匹配行前 N 行（rg -B），与 context 二选一优先用 context",
            },
            "context_after": {
                "type": "integer",
                "description": "content 模式：匹配行后 N 行（rg -A）",
            },
            "multiline": {
                "type": "boolean",
                "description": "正则跨行（rg -U --multiline-dotall），勿与 fixed_string 同用",
                "default": False,
            },
            "head_limit": {
                "type": "integer",
                "description": "最多输出行/条（各模式均适用）；0 表示不限制；省略则用配置",
            },
            "offset": {
                "type": "integer",
                "description": "跳过前 N 行输出再应用 head_limit",
                "default": 0,
            },
        },
        "required": ["query"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        query = (arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, content="", error="query 不能为空")

        sub = (arguments.get("path") or "").strip()
        file_glob = (arguments.get("glob") or "").strip()
        fixed_string = bool(arguments.get("fixed_string", False))
        output_mode = (arguments.get("output_mode") or "files_with_matches").strip()
        if output_mode not in ("content", "files_with_matches", "count"):
            return ToolResult(ok=False, content="", error=f"无效的 output_mode: {output_mode}")

        ignore_case = bool(arguments.get("ignore_case", False))
        file_type = (arguments.get("type") or "").strip() or None
        line_numbers = bool(arguments.get("line_numbers", True))
        multiline = bool(arguments.get("multiline", False))
        if multiline and fixed_string:
            return ToolResult(ok=False, content="", error="multiline 不能与 fixed_string 同时使用")

        ctx_c = arguments.get("context")
        ctx_b = arguments.get("context_before")
        ctx_a = arguments.get("context_after")
        grep_context: int | None = int(ctx_c) if ctx_c is not None else None
        context_before: int | None = int(ctx_b) if ctx_b is not None else None
        context_after: int | None = int(ctx_a) if ctx_a is not None else None

        if "head_limit" in arguments and arguments["head_limit"] is not None:
            head_limit = int(arguments["head_limit"])
        else:
            head_limit = int(context.config.tools.search_default_head_limit)

        offset = int(arguments.get("offset") or 0)
        if offset < 0:
            offset = 0

        try:
            root = context.path_guard.ensure_allowed(sub or ".")
        except ValueError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        timeout = max(5, int(context.config.tools.command_timeout_seconds))
        max_out_chars = int(context.config.tools.command_output_max_chars)

        if not bool(context.config.tools.search_use_ripgrep):
            text = self._python_fallback(
                context,
                query,
                root,
                file_glob=file_glob,
                fixed_string=fixed_string,
                output_mode=output_mode,
                ignore_case=ignore_case,
                file_type=file_type,
                multiline=multiline,
                line_numbers=line_numbers,
                grep_context=grep_context,
                context_before=context_before,
                context_after=context_after,
                head_limit=head_limit,
                offset=offset,
                max_out_chars=max_out_chars,
            )
            return ToolResult(ok=True, content=text)

        cmd = self._build_rg_command(
            query,
            root,
            file_glob=file_glob,
            fixed_string=fixed_string,
            output_mode=output_mode,
            ignore_case=ignore_case,
            file_type=file_type,
            multiline=multiline,
            line_numbers=line_numbers,
            grep_context=grep_context,
            context_before=context_before,
            context_after=context_after,
        )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            text = self._python_fallback(
                context,
                query,
                root,
                file_glob=file_glob,
                fixed_string=fixed_string,
                output_mode=output_mode,
                ignore_case=ignore_case,
                file_type=file_type,
                multiline=multiline,
                line_numbers=line_numbers,
                grep_context=grep_context,
                context_before=context_before,
                context_after=context_after,
                head_limit=head_limit,
                offset=offset,
                max_out_chars=max_out_chars,
            )
            return ToolResult(ok=True, content=text)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, content="", error=f"rg 超时（>{timeout}s）")

        output = proc.stdout.strip()
        if proc.returncode >= 2:
            err = (proc.stderr or proc.stdout or "").strip() or f"rg 退出码 {proc.returncode}"
            return ToolResult(ok=False, content="", error=err[:2000])

        if not output:
            return ToolResult(ok=True, content="(无匹配)")

        lines = output.splitlines()
        lines = self._apply_offset_limit(lines, offset, head_limit)
        text = "\n".join(lines)
        if len(text) > max_out_chars:
            text = text[:max_out_chars] + "\n...[truncated]"
        return ToolResult(ok=True, content=text)

    @staticmethod
    def _apply_offset_limit(lines: list[str], offset: int, head_limit: int) -> list[str]:
        sliced = lines[offset:]
        if head_limit == 0:
            return sliced
        return sliced[:head_limit]

    def _build_rg_command(
        self,
        query: str,
        root: Path,
        *,
        file_glob: str,
        fixed_string: bool,
        output_mode: str,
        ignore_case: bool,
        file_type: str | None,
        multiline: bool,
        line_numbers: bool,
        grep_context: int | None,
        context_before: int | None,
        context_after: int | None,
    ) -> list[str]:
        cmd: list[str] = ["rg", "--color", "never"]
        if output_mode == "files_with_matches":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        else:
            cmd.append("--no-heading")
            if line_numbers:
                cmd.append("-n")
            else:
                cmd.append("--no-line-number")
            if grep_context is not None:
                cmd.extend(["-C", str(max(0, grep_context))])
            else:
                if context_before is not None:
                    cmd.extend(["-B", str(max(0, context_before))])
                if context_after is not None:
                    cmd.extend(["-A", str(max(0, context_after))])

        if fixed_string:
            cmd.append("-F")
        if ignore_case:
            cmd.append("-i")
        if multiline:
            cmd.extend(["-U", "--multiline-dotall"])
        if file_glob:
            cmd.extend(["--glob", file_glob])
        if file_type:
            cmd.extend(["--type", file_type])
        cmd.append("--")
        cmd.append(query)
        cmd.append(str(root))
        return cmd

    def _python_fallback(
        self,
        context: Any,
        query: str,
        root: Path,
        *,
        file_glob: str,
        fixed_string: bool,
        output_mode: str,
        ignore_case: bool,
        file_type: str | None,
        multiline: bool,
        line_numbers: bool,
        grep_context: int | None,
        context_before: int | None,
        context_after: int | None,
        head_limit: int,
        offset: int,
        max_out_chars: int,
    ) -> str:
        ignored = set(context.config.project.ignore_patterns)
        glob_pat = file_glob or ""
        if file_type:
            type_suffixes = _TYPE_SUFFIXES.get(file_type.lower())
        else:
            type_suffixes = None

        flags = re.DOTALL | re.MULTILINE if multiline else 0
        if ignore_case:
            flags |= re.IGNORECASE

        pattern_re: re.Pattern[str] | None = None
        if not fixed_string:
            try:
                pattern_re = re.compile(query, flags)
            except re.error as exc:
                return f"(Python 回退：无效正则 {exc})"

        if output_mode == "files_with_matches":
            paths = self._collect_file_matches(
                root,
                context,
                ignored,
                glob_pat,
                type_suffixes,
                query,
                fixed_string,
                pattern_re,
                multiline,
                ignore_case,
            )
            sliced = self._apply_offset_limit(paths, offset, head_limit)
            out = "\n".join(sliced)
        elif output_mode == "count":
            count_lines: list[str] = []
            for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
                row = self._count_line_for_file(
                    path,
                    context,
                    ignored,
                    glob_pat,
                    type_suffixes,
                    query,
                    fixed_string,
                    pattern_re,
                    multiline,
                    ignore_case,
                )
                if row:
                    count_lines.append(row)
            sliced = self._apply_offset_limit(count_lines, offset, head_limit)
            out = "\n".join(sliced)
        else:
            content_lines: list[str] = []
            for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
                if not self._path_readable_file(path, context, ignored, glob_pat, type_suffixes):
                    continue
                try:
                    if path.stat().st_size > 1024 * 1024:
                        continue
                    raw = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                rel_s = path.relative_to(context.project_root).as_posix()
                content_lines.extend(
                    self._iter_content_lines(
                        rel_s,
                        raw,
                        query,
                        fixed_string,
                        pattern_re,
                        multiline,
                        line_numbers,
                        grep_context,
                        context_before,
                        context_after,
                        ignore_case,
                    )
                )
            sliced = self._apply_offset_limit(content_lines, offset, head_limit)
            out = "\n".join(sliced)

        if not out:
            return "(无匹配，Python 回退)"
        if len(out) > max_out_chars:
            return out[:max_out_chars] + "\n...[truncated]"
        return out

    @staticmethod
    def _path_readable_file(
        path: Path,
        context: Any,
        ignored: set[str],
        glob_pat: str,
        type_suffixes: frozenset[str] | None,
    ) -> bool:
        if not path.is_file():
            return False
        try:
            rel = path.relative_to(context.project_root)
        except ValueError:
            return False
        if ignored.intersection(rel.parts):
            return False
        if glob_pat and not fnmatch(path.name, glob_pat):
            return False
        if type_suffixes is not None and path.suffix.lower() not in {s.lower() for s in type_suffixes}:
            return False
        return True

    def _count_line_for_file(
        self,
        path: Path,
        context: Any,
        ignored: set[str],
        glob_pat: str,
        type_suffixes: frozenset[str] | None,
        query: str,
        fixed_string: bool,
        pattern_re: re.Pattern[str] | None,
        multiline: bool,
        ignore_case: bool,
    ) -> str:
        if not self._path_readable_file(path, context, ignored, glob_pat, type_suffixes):
            return ""
        try:
            if path.stat().st_size > 1024 * 1024:
                return ""
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
        cnt = self._matching_line_count(raw, query, fixed_string, pattern_re, multiline, ignore_case)
        if cnt <= 0:
            return ""
        rel_s = path.relative_to(context.project_root).as_posix()
        return f"{rel_s}:{cnt}"

    @staticmethod
    def _matching_line_count(
        raw: str,
        query: str,
        fixed_string: bool,
        pattern_re: re.Pattern[str] | None,
        multiline: bool,
        ignore_case: bool,
    ) -> int:
        if fixed_string:
            if ignore_case:
                q = query.lower()
                return sum(1 for line in raw.splitlines() if q in line.lower())
            return sum(1 for line in raw.splitlines() if query in line)
        if not pattern_re:
            return 0
        if multiline:
            return 1 if pattern_re.search(raw) else 0
        return sum(1 for line in raw.splitlines() if pattern_re.search(line))

    @staticmethod
    def _file_has_match(
        raw: str,
        query: str,
        fixed_string: bool,
        pattern_re: re.Pattern[str] | None,
        multiline: bool,
        ignore_case: bool,
    ) -> bool:
        if fixed_string:
            if ignore_case:
                return query.lower() in raw.lower()
            return query in raw
        if pattern_re:
            return pattern_re.search(raw) is not None
        return False

    def _collect_file_matches(
        self,
        root: Path,
        context: Any,
        ignored: set[str],
        glob_pat: str,
        type_suffixes: frozenset[str] | None,
        query: str,
        fixed_string: bool,
        pattern_re: re.Pattern[str] | None,
        multiline: bool,
        ignore_case: bool,
    ) -> list[str]:
        found: list[str] = []
        for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
            if not self._path_readable_file(path, context, ignored, glob_pat, type_suffixes):
                continue
            try:
                if path.stat().st_size > 1024 * 1024:
                    continue
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if self._file_has_match(raw, query, fixed_string, pattern_re, multiline, ignore_case):
                found.append(path.relative_to(context.project_root).as_posix())
        return found

    @staticmethod
    def _iter_content_lines(
        rel_s: str,
        raw: str,
        query: str,
        fixed_string: bool,
        pattern_re: re.Pattern[str] | None,
        multiline: bool,
        line_numbers: bool,
        grep_context: int | None,
        context_before: int | None,
        context_after: int | None,
        ignore_case: bool,
    ) -> list[str]:
        lines = raw.splitlines()
        results: list[str] = []

        def before_n() -> int:
            if grep_context is not None:
                return max(0, grep_context)
            return max(0, int(context_before or 0))

        def after_n() -> int:
            if grep_context is not None:
                return max(0, grep_context)
            return max(0, int(context_after or 0))

        b = before_n()
        a = after_n()

        if multiline and pattern_re:
            for m in pattern_re.finditer(raw):
                start_line = raw.count("\n", 0, m.start()) + 1
                snippet = m.group(0).replace("\n", "\\n")
                if line_numbers:
                    results.append(f"{rel_s}:{start_line}:{snippet}")
                else:
                    results.append(f"{rel_s}:{snippet}")
            return results

        for i, line in enumerate(lines):
            if fixed_string:
                ok = query.lower() in line.lower() if ignore_case else query in line
            else:
                ok = pattern_re is not None and pattern_re.search(line) is not None
            if not ok:
                continue
            lo = max(0, i - b)
            hi = min(len(lines), i + a + 1)
            for j in range(lo, hi):
                prefix = f"{rel_s}:{j + 1}:" if line_numbers else f"{rel_s}:"
                results.append(f"{prefix}{lines[j]}")
        return results
