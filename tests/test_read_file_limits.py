"""测试文件读取限制"""
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_agent.tools.file_tools import ReadFileTool
from code_agent.config import ToolConfig, ProjectConfig, AppConfig, ModelConfig
from code_agent.safety.path_guard import PathGuard


class MockContext:
    def __init__(self, project_root):
        self.project_root = project_root
        self.path_guard = PathGuard(project_root, [])
        self.config = AppConfig(
            model=ModelConfig(),
            project=ProjectConfig(),
            tools=ToolConfig(
                read_file_max_size_bytes=1024,  # 1KB for testing
                read_file_max_chars=500,  # 500 chars for testing
            )
        )


def test_file_size_limit():
    """测试文件大小限制"""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)

        # 创建一个超过1KB的文件
        large_file = temp_dir / "large.txt"
        large_file.write_text("x" * 2000, encoding="utf-8")  # 2KB

        tool = ReadFileTool()
        context = MockContext(temp_dir)

        result = tool.execute({"path": str(large_file)}, context)

        print("=" * 60)
        print("测试1: 文件大小限制（2KB > 1KB）")
        print("=" * 60)
        print(f"ok: {result.ok}")
        print(f"error: {result.error}")
        print()

        assert not result.ok
        assert "文件过大" in result.error
        assert "分段读取" in result.error
        print("[OK] 文件大小限制测试通过")


def test_output_size_limit():
    """测试输出大小限制"""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)

        # 创建一个小文件但读取内容超过限制
        file = temp_dir / "medium.txt"
        file.write_text("x" * 800, encoding="utf-8")  # 800 chars

        tool = ReadFileTool()
        context = MockContext(temp_dir)

        result = tool.execute({"path": str(file)}, context)

        print("=" * 60)
        print("测试2: 输出大小限制（800字符 > 500字符）")
        print("=" * 60)
        print(f"ok: {result.ok}")
        print(f"error: {result.error}")
        print()

        assert not result.ok
        assert "输出过大" in result.error
        assert "缩小读取范围" in result.error
        print("[OK] 输出大小限制测试通过")


def test_partial_read():
    """测试分段读取"""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)

        # 创建一个大文件
        file = temp_dir / "big.txt"
        lines = [f"Line {i}\n" for i in range(1000)]
        file.write_text("".join(lines), encoding="utf-8")

        # 使用更大的限制来测试分段读取
        context = MockContext(temp_dir)
        context.config.tools.read_file_max_size_bytes = 20 * 1024  # 20KB
        context.config.tools.read_file_max_chars = 5000  # 5000 chars

        tool = ReadFileTool()

        # 读取前10行
        result = tool.execute({
            "path": str(file),
            "start_line": 1,
            "end_line": 10
        }, context)

        print("=" * 60)
        print("测试3: 分段读取（前10行）")
        print("=" * 60)
        print(f"ok: {result.ok}")
        print(f"content length: {len(result.content)} chars")
        print(f"content preview: {result.content[:100]}...")
        print()

        assert result.ok
        assert "Line 0" in result.content
        assert "Line 9" in result.content
        assert "Line 10" not in result.content
        print("[OK] 分段读取测试通过")


if __name__ == "__main__":
    test_file_size_limit()
    print()
    test_output_size_limit()
    print()
    test_partial_read()
    print()
    print("=" * 60)
    print("[OK] 所有测试通过！")
    print("=" * 60)
