from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_agent.agents.loader import AgentLoader
from code_agent.config import AppConfig
from code_agent.safety.command_guard import CommandGuard
from code_agent.safety.path_guard import PathGuard
from code_agent.schemas import ApprovalProtocol, PendingApproval
from code_agent.skills.loader import SkillLoader
from code_agent.tools.registry import ToolRegistry


@dataclass
class AgentContext:
    config: AppConfig
    project_root: Path
    path_guard: PathGuard
    command_guard: CommandGuard
    skill_loader: SkillLoader
    approval_handler: ApprovalProtocol
    agent_loader: AgentLoader | None = None
    _tool_registry: ToolRegistry | None = None
    selected_skill: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    files_changed: set[str] = field(default_factory=set)
    last_diff: str = ""
    commands_run: list[str] = field(default_factory=list)
    pending_approval: PendingApproval | None = None
    pre_approved_commands: set[str] = field(default_factory=set)
    plan_mode: bool = False
    current_plan_file: Path | None = None
    shell_cwd: Path | None = None  # 会话级持久工作目录，cd 命令更新此值