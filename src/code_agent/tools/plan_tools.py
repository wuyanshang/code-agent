from __future__ import annotations

from pathlib import Path
from typing import Any

from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool


class EnterPlanModeTool(BaseTool):
    name = "enter_plan_mode"
    description = "进入计划模式。在此模式下，只能读取和研究代码，不能修改文件或执行命令。用于在执行前制定详细计划。"
    parameters_schema = {"type": "object", "properties": {}}

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        # 检查是否已在计划模式
        if hasattr(context, "plan_mode") and context.plan_mode:
            return ToolResult(ok=False, content="", error="已经处于计划模式")

        # 设置计划模式标志
        context.plan_mode = True

        # 创建计划文件路径
        plan_dir = context.project_root / ".code-agent" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)

        # 生成计划文件名
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_file = plan_dir / f"plan_{timestamp}.md"
        context.current_plan_file = plan_file

        # 创建计划模板
        template = """# 实施计划

## 任务概述
[在此描述要完成的任务]

## 分析
[分析当前代码状态、问题根源等]

## 实施步骤
1. [步骤1]
2. [步骤2]
3. [步骤3]

## 需要修改的文件
- `文件路径1`: [修改说明]
- `文件路径2`: [修改说明]

## 风险和注意事项
- [风险1]
- [风险2]

## 测试计划
- [测试项1]
- [测试项2]
"""
        plan_file.write_text(template, encoding="utf-8")

        return ToolResult(
            ok=True,
            content=f"已进入计划模式。计划文件: {plan_file}\n\n"
            "在此模式下:\n"
            "- ✅ 可以读取文件、搜索代码\n"
            "- ❌ 不能修改文件\n"
            "- ❌ 不能执行命令\n\n"
            "请分析代码并在计划文件中制定详细方案，完成后使用 exit_plan_mode 退出。",
            metadata={"plan_file": str(plan_file)},
        )


class ExitPlanModeTool(BaseTool):
    name = "exit_plan_mode"
    description = "退出计划模式，恢复正常的文件修改和命令执行能力。通常在计划制定完成并获得用户批准后使用。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "approved": {
                "type": "boolean",
                "description": "计划是否已获得批准",
                "default": False,
            },
        },
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        # 检查是否在计划模式
        if not hasattr(context, "plan_mode") or not context.plan_mode:
            return ToolResult(ok=False, content="", error="当前不在计划模式")

        approved = arguments.get("approved", False)
        plan_file = getattr(context, "current_plan_file", None)

        # 退出计划模式
        context.plan_mode = False

        if approved:
            message = "已退出计划模式，计划已获批准。现在可以开始实施。"
        else:
            message = "已退出计划模式。"

        if plan_file:
            message += f"\n计划文件保存在: {plan_file}"

        return ToolResult(ok=True, content=message)
