"""glob_files 工具测试。"""

from pathlib import Path
from types import SimpleNamespace

from code_agent.config import AppConfig
from code_agent.safety.path_guard import PathGuard
from code_agent.tools.file_tools import GlobFilesTool


def test_glob_files_py(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")

    cfg = AppConfig()
    context = SimpleNamespace(
        path_guard=PathGuard(tmp_path),
        project_root=tmp_path,
        config=cfg,
    )
    result = GlobFilesTool().execute({"pattern": "**/*.py"}, context)
    assert result.ok
    lines = {
        Path(line.strip()).as_posix()
        for line in (result.content or "").splitlines()
        if line.strip()
    }
    assert "src/a.py" in lines


def test_glob_empty_pattern(tmp_path: Path) -> None:
    cfg = AppConfig()
    context = SimpleNamespace(
        path_guard=PathGuard(tmp_path),
        project_root=tmp_path,
        config=cfg,
    )
    result = GlobFilesTool().execute({"pattern": "  "}, context)
    assert not result.ok
