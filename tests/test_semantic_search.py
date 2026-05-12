"""
测试智能代码搜索功能
"""

import ast
from pathlib import Path

from code_agent.tools.semantic_search_tools import (
    PythonASTAnalyzer,
    SearchSymbolTool,
    SearchReferencesTool,
    SearchImportsTool,
)


def test_ast_analyzer():
    """测试 AST 分析器"""
    source = '''
import os
from pathlib import Path

class UserService:
    def login_user(self, username):
        return username

def process_data():
    service = UserService()
    result = service.login_user("test")
    return result
'''

    analyzer = PythonASTAnalyzer("test.py", source)
    tree = ast.parse(source)
    analyzer.visit(tree)

    # 检查符号
    print("=== 符号定义 ===")
    for sym in analyzer.symbols:
        print(f"{sym.type}: {sym.name} at line {sym.line}")

    # 检查导入
    print("\n=== 导入语句 ===")
    for imp in analyzer.imports:
        print(f"{imp.name} at line {imp.line}")

    # 检查引用
    print("\n=== 引用 ===")
    for name, refs in analyzer.references.items():
        print(f"{name}: {len(refs)} 处引用")


if __name__ == "__main__":
    test_ast_analyzer()
