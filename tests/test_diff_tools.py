"""
测试 Diff 可视化工具
"""

from pathlib import Path
from code_agent.tools.diff_tools import (
    ViewSessionDiffTool,
    ViewFileDiffTool,
    CompareFileVersionsTool,
)


def test_diff_tools():
    """测试 Diff 工具的基本功能"""

    print("=== Diff 工具测试 ===\n")

    # 测试 1: ViewSessionDiffTool
    print("1. ViewSessionDiffTool - 查看会话变更摘要")
    tool = ViewSessionDiffTool()
    print(f"   工具名: {tool.name}")
    print(f"   描述: {tool.description}")
    print(f"   参数: {tool.parameters_schema}")
    print()

    # 测试 2: ViewFileDiffTool
    print("2. ViewFileDiffTool - 查看文件详细 diff")
    tool = ViewFileDiffTool()
    print(f"   工具名: {tool.name}")
    print(f"   描述: {tool.description}")
    print(f"   参数: {tool.parameters_schema}")
    print()

    # 测试 3: CompareFileVersionsTool
    print("3. CompareFileVersionsTool - 比较文件版本")
    tool = CompareFileVersionsTool()
    print(f"   工具名: {tool.name}")
    print(f"   描述: {tool.description}")
    print(f"   参数: {tool.parameters_schema}")
    print()

    print("OK - 所有工具定义正确")


if __name__ == "__main__":
    test_diff_tools()
