"""format_tool_error_for_model 单元测试。"""

from code_agent.utils.errors import format_tool_error_for_model


def test_short_error_unchanged() -> None:
    assert format_tool_error_for_model("permission denied") == "permission denied"


def test_long_plain_truncated() -> None:
    long_msg = "x" * 1000
    out = format_tool_error_for_model(long_msg, max_chars=100)
    assert len(out) <= 102
    assert out.endswith("…")


def test_traceback_collapsed() -> None:
    tb = """Traceback (most recent call last):
  File "a.py", line 1, in <module>
    raise RuntimeError("boom")
RuntimeError: boom"""
    out = format_tool_error_for_model(tb)
    assert out.startswith("Traceback")
    assert "完整堆栈已省略" in out
    assert 'File "a.py"' not in out


def test_file_line_pattern_collapsed() -> None:
    s = 'File "C:\\\\proj\\\\x.py", line 99, in foo\nValueError: bad'
    out = format_tool_error_for_model(s)
    assert "完整堆栈已省略" in out
