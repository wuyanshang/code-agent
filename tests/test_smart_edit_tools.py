from pathlib import Path
from tempfile import TemporaryDirectory

from code_agent.tools.smart_edit_tools import (
    DeleteLinesTool,
    InsertLinesTool,
    SmartReplaceTool,
    adjust_indent,
    detect_indentation,
    get_line_indent,
)


class MockContext:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.files_changed = set()
        self.last_diff = ""

    class PathGuard:
        def __init__(self, root: Path) -> None:
            self.root = root

        def ensure_allowed(self, path: str) -> Path:
            return self.root / path

    @property
    def path_guard(self):
        return self.PathGuard(self.project_root)


def test_detect_indentation_spaces():
    content = """def foo():
    if True:
        print("hello")
        print("world")
"""
    indent_type, indent_size = detect_indentation(content)
    assert indent_type == "space"
    assert indent_size == 4


def test_detect_indentation_tabs():
    content = """def foo():
\tif True:
\t\tprint("hello")
"""
    indent_type, indent_size = detect_indentation(content)
    assert indent_type == "tab"
    assert indent_size == 1


def test_detect_indentation_two_spaces():
    content = """def foo():
  if True:
    print("hello")
"""
    indent_type, indent_size = detect_indentation(content)
    assert indent_type == "space"
    assert indent_size == 2


def test_get_line_indent():
    assert get_line_indent("    hello") == "    "
    assert get_line_indent("\t\thello") == "\t\t"
    assert get_line_indent("hello") == ""


def test_adjust_indent():
    text = "line1\n  line2\n    line3"
    adjusted = adjust_indent(text, "    ")
    lines = adjusted.splitlines()
    assert lines[0] == "    line1"
    assert lines[1] == "      line2"  # 原有2空格 + 目标4空格
    assert lines[2] == "        line3"  # 原有4空格 + 目标4空格


def test_smart_replace_simple():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text("hello world\nhello python\n")

        context = MockContext(project_root)
        tool = SmartReplaceTool()

        result = tool.execute(
            {"path": "test.py", "old_text": "hello", "new_text": "hi"},
            context,
        )

        assert result.ok
        content = test_file.read_text()
        assert content == "hi world\nhello python\n"  # 只替换第一个


def test_smart_replace_all():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text("hello world\nhello python\n")

        context = MockContext(project_root)
        tool = SmartReplaceTool()

        result = tool.execute(
            {"path": "test.py", "old_text": "hello", "new_text": "hi", "count": -1},
            context,
        )

        assert result.ok
        content = test_file.read_text()
        assert content == "hi world\nhi python\n"  # 替换所有


def test_smart_replace_with_indent():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text(
            """def foo():
    old_code
    return True
"""
        )

        context = MockContext(project_root)
        tool = SmartReplaceTool()

        result = tool.execute(
            {
                "path": "test.py",
                "old_text": "old_code",
                "new_text": "if x:\n    new_code()",
                "preserve_indent": True,
            },
            context,
        )

        assert result.ok
        content = test_file.read_text()
        # 新代码应该保持原有的4空格缩进
        assert "    if x:" in content
        assert "        new_code()" in content


def test_smart_replace_regex():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text("value1 = 10\nvalue2 = 20\n")

        context = MockContext(project_root)
        tool = SmartReplaceTool()

        result = tool.execute(
            {
                "path": "test.py",
                "old_text": r"value(\d+)",
                "new_text": r"var\1",
                "regex": True,
                "count": -1,
            },
            context,
        )

        assert result.ok
        content = test_file.read_text()
        assert content == "var1 = 10\nvar2 = 20\n"


def test_insert_lines():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        context = MockContext(project_root)
        tool = InsertLinesTool()

        result = tool.execute(
            {"path": "test.py", "line_number": 2, "content": "inserted"},
            context,
        )

        assert result.ok
        content = test_file.read_text()
        lines = content.splitlines()
        assert lines[0] == "line1"
        assert lines[1] == "inserted"
        assert lines[2] == "line2"
        assert lines[3] == "line3"


def test_insert_lines_with_indent():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text(
            """def foo():
    line1
    line2
"""
        )

        context = MockContext(project_root)
        tool = InsertLinesTool()

        result = tool.execute(
            {
                "path": "test.py",
                "line_number": 3,
                "content": "inserted",
                "match_indent": True,
            },
            context,
        )

        assert result.ok
        content = test_file.read_text()
        # 插入的内容应该匹配line2的缩进（4空格）
        assert "    inserted" in content


def test_delete_lines_single():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        context = MockContext(project_root)
        tool = DeleteLinesTool()

        result = tool.execute(
            {"path": "test.py", "start_line": 2},
            context,
        )

        assert result.ok
        content = test_file.read_text()
        lines = content.splitlines()
        assert len(lines) == 2
        assert lines[0] == "line1"
        assert lines[1] == "line3"


def test_delete_lines_range():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        context = MockContext(project_root)
        tool = DeleteLinesTool()

        result = tool.execute(
            {"path": "test.py", "start_line": 2, "end_line": 4},
            context,
        )

        assert result.ok
        content = test_file.read_text()
        lines = content.splitlines()
        assert len(lines) == 2
        assert lines[0] == "line1"
        assert lines[1] == "line5"


def test_smart_replace_not_found():
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        test_file = project_root / "test.py"
        test_file.write_text("hello world\n")

        context = MockContext(project_root)
        tool = SmartReplaceTool()

        result = tool.execute(
            {"path": "test.py", "old_text": "notfound", "new_text": "replacement"},
            context,
        )

        assert not result.ok
        assert "未找到" in result.error
