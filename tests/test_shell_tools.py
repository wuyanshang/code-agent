from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from code_agent.config import AppConfig
from code_agent.safety.command_guard import CommandGuard
from code_agent.tools.shell_tools import RunCommandTool


class _ApprovalHandler:
    def is_approved(self, command: str, reason: str) -> bool:
        return True


def test_run_command_uses_argv_execution(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr("code_agent.tools.shell_tools.subprocess.run", fake_run)

    config = AppConfig()
    context = SimpleNamespace(
        command_guard=CommandGuard(config.command_policy),
        approval_handler=_ApprovalHandler(),
        pending_approval=None,
        pre_approved_commands=set(),
        project_root=tmp_path,
        config=config,
        commands_run=[],
    )

    result = RunCommandTool().execute({"command": "git status"}, context)

    assert result.ok is True
    assert len(calls) == 1
    assert calls[0]["args"] == (["git", "status"],)
    assert calls[0]["kwargs"]["shell"] is False
