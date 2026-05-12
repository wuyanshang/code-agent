from pathlib import Path
from tempfile import TemporaryDirectory

from code_agent.tools.plan_tools import EnterPlanModeTool, ExitPlanModeTool


class MockContext:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.plan_mode = False
        self.current_plan_file = None


def test_enter_plan_mode() -> None:
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        tool = EnterPlanModeTool()

        result = tool.execute({}, context)

        assert result.ok
        assert context.plan_mode is True
        assert "已进入计划模式" in result.content
        assert context.current_plan_file is not None
        assert context.current_plan_file.exists()

        # 检查计划文件内容
        content = context.current_plan_file.read_text(encoding="utf-8")
        assert "# 实施计划" in content
        assert "## 任务概述" in content
        assert "## 实施步骤" in content


def test_enter_plan_mode_already_in_plan_mode() -> None:
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        context.plan_mode = True
        tool = EnterPlanModeTool()

        result = tool.execute({}, context)

        assert not result.ok
        assert "已经处于计划模式" in result.error


def test_exit_plan_mode() -> None:
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        context.plan_mode = True
        context.current_plan_file = Path(tmpdir) / "plan.md"
        context.current_plan_file.write_text("test plan")

        tool = ExitPlanModeTool()
        result = tool.execute({"approved": True}, context)

        assert result.ok
        assert context.plan_mode is False
        assert "已退出计划模式" in result.content
        assert "已获批准" in result.content


def test_exit_plan_mode_not_in_plan_mode() -> None:
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))
        context.plan_mode = False

        tool = ExitPlanModeTool()
        result = tool.execute({}, context)

        assert not result.ok
        assert "当前不在计划模式" in result.error


def test_plan_mode_workflow() -> None:
    """测试完整的计划模式工作流"""
    with TemporaryDirectory() as tmpdir:
        context = MockContext(Path(tmpdir))

        # 1. 进入计划模式
        enter_tool = EnterPlanModeTool()
        result = enter_tool.execute({}, context)
        assert result.ok
        assert context.plan_mode is True
        plan_file = context.current_plan_file

        # 2. 修改计划文件（模拟用户编辑）
        plan_content = plan_file.read_text(encoding="utf-8")
        plan_content = plan_content.replace(
            "[在此描述要完成的任务]",
            "实现用户认证功能"
        )
        plan_file.write_text(plan_content, encoding="utf-8")

        # 3. 退出计划模式
        exit_tool = ExitPlanModeTool()
        result = exit_tool.execute({"approved": True}, context)
        assert result.ok
        assert context.plan_mode is False

        # 4. 验证计划文件仍然存在
        assert plan_file.exists()
        content = plan_file.read_text(encoding="utf-8")
        assert "实现用户认证功能" in content
