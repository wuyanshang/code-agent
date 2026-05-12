from __future__ import annotations

from typing import Callable

from code_agent.agent.runner import AgentRunner
from code_agent.config import AppConfig
from code_agent.llm import create_llm_client
from code_agent.teams.config import AgentRoleConfig, TeamConfig
from code_agent.teams.orchestrator import TeamOrchestrator
from code_agent.tools.edit_tools import AppendFileTool, PreviewDiffTool, ReplaceInFileTool, WriteFileTool
from code_agent.tools.diff_tools import ViewSessionDiffTool, ViewFileDiffTool, CompareFileVersionsTool
from code_agent.tools.smart_edit_tools import DeleteLinesTool, InsertLinesTool, SmartReplaceTool
from code_agent.tools.file_tools import FindFilesTool, GlobFilesTool, ListFilesTool, ReadFileTool
from code_agent.tools.table_file_tools import ReadTableFileTool
from code_agent.tools.registry import ToolRegistry
from code_agent.tools.search_tools import SearchTextTool
from code_agent.tools.semantic_search_tools import (
    SearchSymbolTool,
    SearchReferencesTool,
    SearchImportsTool,
)
from code_agent.tools.shell_tools import RunCommandTool
from code_agent.tools.background_command_tools import (
    GetCommandOutputTool,
    ListBackgroundCommandsTool,
    RunCommandBackgroundTool,
    StopCommandTool,
)
from code_agent.tools.agent_tools import DelegateAgentTool, ListAgentsTool, TaskTool
from code_agent.tools.skill_tools import InvokeSkillTool, ListSkillsTool, ReadSkillTool
from code_agent.tools.task_tools import TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool
from code_agent.tools.interaction_tools import AskUserQuestionTool
from code_agent.tools.plan_tools import EnterPlanModeTool, ExitPlanModeTool


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in [
        ListFilesTool(),
        ReadFileTool(),
        ReadTableFileTool(),
        FindFilesTool(),
        GlobFilesTool(),
        SearchTextTool(),
        # 智能代码搜索（基于 AST）
        SearchSymbolTool(),
        SearchReferencesTool(),
        SearchImportsTool(),
        WriteFileTool(),
        ReplaceInFileTool(),
        AppendFileTool(),
        PreviewDiffTool(),
        # Diff 可视化工具
        ViewSessionDiffTool(),
        ViewFileDiffTool(),
        CompareFileVersionsTool(),
        # 智能编辑工具
        SmartReplaceTool(),
        InsertLinesTool(),
        DeleteLinesTool(),
        RunCommandTool(),
        # 后台命令执行
        RunCommandBackgroundTool(),
        GetCommandOutputTool(),
        StopCommandTool(),
        ListBackgroundCommandsTool(),
        ListSkillsTool(),
        ReadSkillTool(),
        InvokeSkillTool(),
        ListAgentsTool(),
        DelegateAgentTool(),
        TaskTool(),           # delegate_agent 的别名，兼容 claude-code Task 工具调用约定
        # P0 核心功能
        TaskCreateTool(),
        TaskUpdateTool(),
        TaskListTool(),
        TaskGetTool(),
        AskUserQuestionTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
    ]:
        registry.register(tool)
    return registry


def build_runner(config: AppConfig, interactive: bool = True) -> AgentRunner:
    return AgentRunner(
        config=config,
        llm_client=create_llm_client(config.model),
        tool_registry=build_tool_registry(),
        interactive=interactive,
    )


def build_team_orchestrator(config: AppConfig, progress_callback: Callable[[str], None] | None = None) -> TeamOrchestrator:
    team_cfg = TeamConfig(
        mode=config.team.mode,
        max_parallel=config.team.max_parallel,
        max_rounds=config.team.max_rounds,
        timeout_seconds=config.team.timeout_seconds,
        max_retries=config.team.max_retries,
        max_context_messages=config.team.max_context_messages,
        trim_keep_recent=config.team.trim_keep_recent,
        max_total_tokens=config.team.max_total_tokens,
        checkpoint_dir=config.team.checkpoint_dir,
        roles=[
            AgentRoleConfig(
                name=r.name,
                role=r.role,
                tools=r.tools,
                system_prompt_extra=r.system_prompt_extra,
            )
            for r in config.team.roles
        ],
    )
    return TeamOrchestrator(
        team_config=team_cfg,
        app_config=config,
        llm_client=create_llm_client(config.model),
        tool_registry=build_tool_registry(),
        progress_callback=progress_callback,
    )
