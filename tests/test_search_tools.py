"""search_text 工具：rg 命令构造与 Python 回退。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from code_agent.config import AppConfig
from code_agent.safety.path_guard import PathGuard
from code_agent.tools.search_tools import SearchTextTool


def _ctx(tmp: Path) -> SimpleNamespace:
    cfg = AppConfig()
    return SimpleNamespace(
        path_guard=PathGuard(tmp),
        project_root=tmp,
        config=cfg,
    )


def test_build_rg_content_default(tmp_path: Path) -> None:
    tool = SearchTextTool()
    cmd = tool._build_rg_command(
        "foo",
        tmp_path,
        file_glob="*.py",
        fixed_string=True,
        output_mode="content",
        ignore_case=True,
        file_type="py",
        multiline=False,
        line_numbers=True,
        grep_context=None,
        context_before=None,
        context_after=None,
    )
    assert cmd[0] == "rg"
    assert "-F" in cmd
    assert "-i" in cmd
    assert "--glob" in cmd
    assert "--type" in cmd
    assert "py" in cmd
    assert cmd[-3] == "--"
    assert cmd[-2] == "foo"
    assert cmd[-1] == str(tmp_path)


def test_build_rg_files_with_matches(tmp_path: Path) -> None:
    tool = SearchTextTool()
    cmd = tool._build_rg_command(
        "pat",
        tmp_path,
        file_glob="",
        fixed_string=False,
        output_mode="files_with_matches",
        ignore_case=False,
        file_type=None,
        multiline=False,
        line_numbers=True,
        grep_context=None,
        context_before=None,
        context_after=None,
    )
    assert "-l" in cmd
    assert "-n" not in cmd


def test_build_rg_count(tmp_path: Path) -> None:
    tool = SearchTextTool()
    cmd = tool._build_rg_command(
        "pat",
        tmp_path,
        file_glob="",
        fixed_string=False,
        output_mode="count",
        ignore_case=False,
        file_type=None,
        multiline=False,
        line_numbers=True,
        grep_context=None,
        context_before=None,
        context_after=None,
    )
    assert "-c" in cmd


def test_build_rg_context_c(tmp_path: Path) -> None:
    tool = SearchTextTool()
    cmd = tool._build_rg_command(
        "x",
        tmp_path,
        file_glob="",
        fixed_string=False,
        output_mode="content",
        ignore_case=False,
        file_type=None,
        multiline=False,
        line_numbers=True,
        grep_context=2,
        context_before=None,
        context_after=None,
    )
    assert "-C" in cmd
    i = cmd.index("-C")
    assert cmd[i + 1] == "2"


def test_apply_offset_limit() -> None:
    assert SearchTextTool._apply_offset_limit(["a", "b", "c"], 1, 0) == ["b", "c"]
    assert SearchTextTool._apply_offset_limit(["a", "b", "c"], 0, 2) == ["a", "b"]
    assert SearchTextTool._apply_offset_limit(["a", "b"], 1, 10) == ["b"]


@patch("code_agent.tools.search_tools.subprocess.run")
def test_execute_rg_success_slice(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "a\nb\nc\nd\n"
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    tool = SearchTextTool()
    cfg = AppConfig()
    cfg.tools.search_use_ripgrep = True
    ctx = SimpleNamespace(
        path_guard=PathGuard(tmp_path),
        project_root=tmp_path,
        config=cfg,
    )
    result = tool.execute(
        {"query": "q", "output_mode": "content", "head_limit": 2, "offset": 1},
        ctx,
    )
    assert result.ok
    mock_run.assert_called_once()
    assert result.content == "b\nc"


@patch("code_agent.tools.search_tools.subprocess.run", side_effect=FileNotFoundError)
def test_execute_python_fallback_files_mode(_mock: MagicMock, tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("hello\n", encoding="utf-8")
    (tmp_path / "y.txt").write_text("hello\n", encoding="utf-8")

    tool = SearchTextTool()
    ctx = _ctx(tmp_path)
    result = tool.execute(
        {"query": "hello", "fixed_string": True, "output_mode": "files_with_matches"},
        ctx,
    )
    assert result.ok
    lines = {Path(p).as_posix() for p in result.content.splitlines() if p.strip()}
    assert "x.py" in lines
    assert "y.txt" in lines


@patch("code_agent.tools.search_tools.subprocess.run", side_effect=FileNotFoundError)
def test_execute_python_fallback_count(_mock: MagicMock, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a\na\nb\n", encoding="utf-8")

    tool = SearchTextTool()
    ctx = _ctx(tmp_path)
    result = tool.execute(
        {
            "query": "a",
            "fixed_string": True,
            "output_mode": "count",
            "glob": "*.py",
        },
        ctx,
    )
    assert result.ok
    assert "a.py:2" in result.content


def test_empty_query(tmp_path: Path) -> None:
    tool = SearchTextTool()
    r = tool.execute({"query": "   "}, _ctx(tmp_path))
    assert not r.ok


@patch("code_agent.tools.search_tools.subprocess.run", side_effect=FileNotFoundError)
def test_fallback_unknown_type_still_ok_python(_mock: MagicMock, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    tool = SearchTextTool()
    ctx = _ctx(tmp_path)
    r = tool.execute({"query": "x", "type": "not_a_builtin_type"}, ctx)
    assert r.ok
    assert "a.txt" in r.content


def test_default_search_use_ripgrep_false_skips_subprocess(tmp_path: Path) -> None:
    cfg = AppConfig()
    assert cfg.tools.search_use_ripgrep is False
    ctx = SimpleNamespace(
        path_guard=PathGuard(tmp_path),
        project_root=tmp_path,
        config=cfg,
    )
    (tmp_path / "b.py").write_text("unique_marker_xyz\n", encoding="utf-8")
    with patch("code_agent.tools.search_tools.subprocess.run") as mock_run:
        r = SearchTextTool().execute({"query": "unique_marker_xyz", "fixed_string": True}, ctx)
    mock_run.assert_not_called()
    assert r.ok
    assert "b.py" in r.content


@patch("code_agent.tools.search_tools.subprocess.run")
def test_head_limit_uses_search_default_head_limit(mock_run: MagicMock, tmp_path: Path) -> None:
    lines = "\n".join(f"f{i}.txt" for i in range(300))
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = lines
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    cfg = AppConfig()
    cfg.tools.search_use_ripgrep = True
    cfg.tools.search_default_head_limit = 5
    ctx = SimpleNamespace(
        path_guard=PathGuard(tmp_path),
        project_root=tmp_path,
        config=cfg,
    )
    result = SearchTextTool().execute({"query": "pat"}, ctx)
    assert result.ok
    assert len(result.content.splitlines()) == 5


def test_multiline_with_fixed_string_rejected(tmp_path: Path) -> None:
    tool = SearchTextTool()
    r = tool.execute(
        {"query": "a", "fixed_string": True, "multiline": True},
        _ctx(tmp_path),
    )
    assert not r.ok
