"""
智能代码搜索工具 - 基于 AST 的语义搜索

提供比纯文本搜索更精确的代码搜索能力：
- search_symbol: 查找类、函数、变量定义
- search_references: 查找符号的所有引用
- search_imports: 查找导入语句
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool


class SymbolInfo:
    """符号信息"""

    def __init__(
        self,
        name: str,
        type: str,
        file: str,
        line: int,
        col: int = 0,
        end_line: int | None = None,
    ):
        self.name = name
        self.type = type  # class, function, variable, import
        self.file = file
        self.line = line
        self.col = col
        self.end_line = end_line

    def __repr__(self) -> str:
        return f"{self.file}:{self.line}:{self.col}"


class PythonASTAnalyzer(ast.NodeVisitor):
    """Python AST 分析器"""

    def __init__(self, file_path: str, source: str):
        self.file_path = file_path
        self.source = source
        self.symbols: list[SymbolInfo] = []
        self.references: dict[str, list[SymbolInfo]] = {}
        self.imports: list[SymbolInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """访问类定义"""
        self.symbols.append(
            SymbolInfo(
                name=node.name,
                type="class",
                file=self.file_path,
                line=node.lineno,
                col=node.col_offset,
                end_line=node.end_lineno,
            )
        )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """访问函数定义"""
        self.symbols.append(
            SymbolInfo(
                name=node.name,
                type="function",
                file=self.file_path,
                line=node.lineno,
                col=node.col_offset,
                end_line=node.end_lineno,
            )
        )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """访问异步函数定义"""
        self.symbols.append(
            SymbolInfo(
                name=node.name,
                type="function",
                file=self.file_path,
                line=node.lineno,
                col=node.col_offset,
                end_line=node.end_lineno,
            )
        )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """访问 import 语句"""
        for alias in node.names:
            self.imports.append(
                SymbolInfo(
                    name=alias.name,
                    type="import",
                    file=self.file_path,
                    line=node.lineno,
                    col=node.col_offset,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """访问 from ... import 语句"""
        module = node.module or ""
        for alias in node.names:
            import_name = f"{module}.{alias.name}" if module else alias.name
            self.imports.append(
                SymbolInfo(
                    name=import_name,
                    type="import",
                    file=self.file_path,
                    line=node.lineno,
                    col=node.col_offset,
                )
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """访问名称引用"""
        if isinstance(node.ctx, ast.Load):
            if node.id not in self.references:
                self.references[node.id] = []
            self.references[node.id].append(
                SymbolInfo(
                    name=node.id,
                    type="reference",
                    file=self.file_path,
                    line=node.lineno,
                    col=node.col_offset,
                )
            )
        self.generic_visit(node)


class SearchSymbolTool(BaseTool):
    """搜索符号定义（类、函数、变量）"""

    name = "search_symbol"
    description = (
        "在项目中搜索符号定义（类、函数等）。"
        "比 search_text 更精确，只返回真正的定义位置，不包括注释、字符串、引用。"
        "支持 Python 文件的 AST 分析。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "符号名称，如 UserService、login_user",
            },
            "symbol_type": {
                "type": "string",
                "enum": ["class", "function", "any"],
                "description": "符号类型：class=类定义，function=函数定义，any=任意类型",
                "default": "any",
            },
            "path": {
                "type": "string",
                "description": "搜索路径（相对项目根），默认全项目",
            },
        },
        "required": ["name"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        symbol_name = arguments.get("name", "").strip()
        if not symbol_name:
            return ToolResult(ok=False, content="", error="name 不能为空")

        symbol_type = arguments.get("symbol_type", "any").strip()
        search_path = arguments.get("path", "").strip()

        try:
            root = context.path_guard.ensure_allowed(search_path or ".")
        except ValueError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        results = self._search_in_directory(
            root, symbol_name, symbol_type, context
        )

        if not results:
            return ToolResult(ok=True, content=f"未找到符号: {symbol_name}")

        lines = [f"找到 {len(results)} 个定义:"]
        for sym in results:
            rel_path = Path(sym.file).relative_to(context.project_root).as_posix()
            lines.append(f"  {rel_path}:{sym.line} - {sym.type} {sym.name}")

        return ToolResult(ok=True, content="\n".join(lines))

    def _search_in_directory(
        self,
        root: Path,
        symbol_name: str,
        symbol_type: str,
        context: Any,
    ) -> list[SymbolInfo]:
        results: list[SymbolInfo] = []
        ignored = set(context.config.project.ignore_patterns)

        for py_file in root.rglob("*.py"):
            try:
                rel = py_file.relative_to(context.project_root)
            except ValueError:
                continue
            if ignored.intersection(rel.parts):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue

            analyzer = PythonASTAnalyzer(str(py_file), source)
            analyzer.visit(tree)

            for sym in analyzer.symbols:
                if sym.name == symbol_name:
                    if symbol_type == "any" or sym.type == symbol_type:
                        results.append(sym)

        return results


class SearchReferencesTool(BaseTool):
    """搜索符号的所有引用"""

    name = "search_references"
    description = (
        "查找符号在项目中的所有引用位置。"
        "比 search_text 更智能，能区分定义和引用，只返回真正的使用点。"
        "支持 Python 文件的 AST 分析。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "符号名称，如 login_user、UserService",
            },
            "path": {
                "type": "string",
                "description": "搜索路径（相对项目根），默认全项目",
            },
            "include_definition": {
                "type": "boolean",
                "description": "是否包含定义位置",
                "default": False,
            },
        },
        "required": ["symbol"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        symbol = arguments.get("symbol", "").strip()
        if not symbol:
            return ToolResult(ok=False, content="", error="symbol 不能为空")

        search_path = arguments.get("path", "").strip()
        include_def = bool(arguments.get("include_definition", False))

        try:
            root = context.path_guard.ensure_allowed(search_path or ".")
        except ValueError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        refs, defs = self._search_references(root, symbol, context)

        if not refs and not defs:
            return ToolResult(ok=True, content=f"未找到符号引用: {symbol}")

        lines = []
        if defs and include_def:
            lines.append(f"定义 ({len(defs)} 处):")
            for sym in defs[:10]:
                rel_path = Path(sym.file).relative_to(context.project_root).as_posix()
                lines.append(f"  {rel_path}:{sym.line}")

        if refs:
            lines.append(f"引用 ({len(refs)} 处):")
            for sym in refs[:50]:
                rel_path = Path(sym.file).relative_to(context.project_root).as_posix()
                lines.append(f"  {rel_path}:{sym.line}")
            if len(refs) > 50:
                lines.append(f"  ... 还有 {len(refs) - 50} 处引用")

        return ToolResult(ok=True, content="\n".join(lines))

    def _search_references(
        self,
        root: Path,
        symbol: str,
        context: Any,
    ) -> tuple[list[SymbolInfo], list[SymbolInfo]]:
        references: list[SymbolInfo] = []
        definitions: list[SymbolInfo] = []
        ignored = set(context.config.project.ignore_patterns)

        for py_file in root.rglob("*.py"):
            try:
                rel = py_file.relative_to(context.project_root)
            except ValueError:
                continue
            if ignored.intersection(rel.parts):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue

            analyzer = PythonASTAnalyzer(str(py_file), source)
            analyzer.visit(tree)

            for sym in analyzer.symbols:
                if sym.name == symbol:
                    definitions.append(sym)

            if symbol in analyzer.references:
                references.extend(analyzer.references[symbol])

        return references, definitions


class SearchImportsTool(BaseTool):
    """搜索导入语句"""

    name = "search_imports"
    description = (
        "查找项目中所有导入特定包或模块的位置。"
        "支持 import xxx 和 from xxx import yyy 两种形式。"
        "支持 Python 文件的 AST 分析。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": "包或模块名称，如 flask、os.path",
            },
            "path": {
                "type": "string",
                "description": "搜索路径（相对项目根），默认全项目",
            },
        },
        "required": ["package"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        package = arguments.get("package", "").strip()
        if not package:
            return ToolResult(ok=False, content="", error="package 不能为空")

        search_path = arguments.get("path", "").strip()

        try:
            root = context.path_guard.ensure_allowed(search_path or ".")
        except ValueError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        results = self._search_imports(root, package, context)

        if not results:
            return ToolResult(ok=True, content=f"未找到导入: {package}")

        lines = [f"找到 {len(results)} 处导入:"]
        for sym in results[:50]:
            rel_path = Path(sym.file).relative_to(context.project_root).as_posix()
            lines.append(f"  {rel_path}:{sym.line} - {sym.name}")
        if len(results) > 50:
            lines.append(f"  ... 还有 {len(results) - 50} 处导入")

        return ToolResult(ok=True, content="\n".join(lines))

    def _search_imports(
        self,
        root: Path,
        package: str,
        context: Any,
    ) -> list[SymbolInfo]:
        results: list[SymbolInfo] = []
        ignored = set(context.config.project.ignore_patterns)

        for py_file in root.rglob("*.py"):
            try:
                rel = py_file.relative_to(context.project_root)
            except ValueError:
                continue
            if ignored.intersection(rel.parts):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue

            analyzer = PythonASTAnalyzer(str(py_file), source)
            analyzer.visit(tree)

            for imp in analyzer.imports:
                if imp.name == package or imp.name.startswith(f"{package}."):
                    results.append(imp)

        return results
