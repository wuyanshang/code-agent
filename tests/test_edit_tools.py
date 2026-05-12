from pathlib import Path
from types import SimpleNamespace

from code_agent.config import AppConfig
from code_agent.safety.path_guard import PathGuard
from code_agent.tools.edit_tools import ReplaceInFileTool


def test_replace_in_file(tmp_path: Path) -> None:
    file_path = tmp_path / "demo.txt"
    file_path.write_text("hello world", encoding="utf-8")
    context = SimpleNamespace(
        path_guard=PathGuard(tmp_path),
        project_root=tmp_path,
        files_changed=set(),
        last_diff="",
        config=AppConfig(),
    )
    result = ReplaceInFileTool().execute(
        {"path": "demo.txt", "old_text": "world", "new_text": "agent"},
        context,
    )
    assert result.ok
    assert "agent" in file_path.read_text(encoding="utf-8")
