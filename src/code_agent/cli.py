from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import typer

from code_agent.app import build_runner, build_team_orchestrator, build_tool_registry
from code_agent.config import load_config
from code_agent.schemas import ExecutionResult
from code_agent.services.logging_service import configure_logging
from code_agent.skills.loader import SkillLoader
from code_agent.teams.orchestrator import TeamResult
from code_agent.utils.json_utils import json_safe

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

app = typer.Typer(help="Local coding assistant with skills and guarded command execution.")
skills_app = typer.Typer(help="Manage and inspect skills.")
tools_app = typer.Typer(help="Inspect available tools.")
team_app = typer.Typer(help="Run tasks with an agent team.")
app.add_typer(skills_app, name="skills")
app.add_typer(tools_app, name="tools")
app.add_typer(team_app, name="team")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    project: str = typer.Option(".", "--project", help="Project root directory."),
    config: str = typer.Option("config/default.yaml", "--config", help="Path to config YAML."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip all command approvals."),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    loaded = load_config(config)
    loaded.project.root = project
    configure_logging(loaded.logging.level)

    from code_agent.llm import create_llm_client
    from code_agent.repl.session import ReplSession

    llm_client = create_llm_client(loaded.model)
    registry = build_tool_registry()
    session = ReplSession(
        config=loaded,
        llm_client=llm_client,
        tool_registry=registry,
        project_root=Path(project).resolve(),
        auto_approve=yes,
    )

    async def _run_repl() -> None:
        try:
            await session.start()
        finally:
            await llm_client.close()

    try:
        asyncio.run(_run_repl())
    except (KeyboardInterrupt, SystemExit):
        pass


@app.command()
def run(
    task: str,
    project: str = typer.Option(".", "--project", help="Project root directory."),
    skill: str | None = typer.Option(None, "--skill", help="Skill name to load."),
    config: str = typer.Option("config/default.yaml", "--config", help="Path to config YAML."),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", help="Allow interactive approvals."),
) -> None:
    loaded = load_config(config)
    loaded.project.root = project
    configure_logging(loaded.logging.level)
    runner = build_runner(loaded, interactive=interactive)

    async def _run() -> ExecutionResult:
        try:
            return await runner.run(task=task, project_root=project, skill=skill)
        finally:
            await runner.llm_client.close()

    result = asyncio.run(_run())
    typer.echo(json.dumps(
        {
            "final_answer": result.final_answer,
            "tool_calls": json_safe(result.tool_calls),
            "files_changed": result.files_changed,
            "diff_preview": result.diff_preview,
            "commands_run": result.commands_run,
            "skill_used": result.skill_used,
            "stopped_reason": result.stopped_reason,
            "pending_approval": None if result.pending_approval is None else {
                "command": result.pending_approval.command,
                "reason": result.pending_approval.reason,
                "decision": result.pending_approval.decision.value,
            },
        },
        ensure_ascii=False,
        indent=2,
    ))


@team_app.command("run")
def team_run(
    task: str,
    project: str = typer.Option(".", "--project", help="Project root directory."),
    config: str = typer.Option("config/default.yaml", "--config", help="Path to config YAML."),
    checkpoint: str | None = typer.Option(None, "--checkpoint", help="Resume from checkpoint file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress messages."),
) -> None:
    loaded = load_config(config)
    loaded.project.root = project
    configure_logging(loaded.logging.level)

    # 进度回调
    def progress_callback(msg: str) -> None:
        if verbose:
            typer.echo(f"[进度] {msg}", err=True)

    orchestrator = build_team_orchestrator(loaded, progress_callback=progress_callback if verbose else None)

    async def _run_team() -> TeamResult:
        try:
            checkpoint_path = Path(checkpoint) if checkpoint else None
            return await orchestrator.run(task=task, project_root=project, checkpoint_path=checkpoint_path)
        finally:
            await orchestrator.llm_client.close()

    result = asyncio.run(_run_team())
    output = {
        "task": result.task,
        "summary": result.summary,
        "decision": result.decision,
        "confidence": result.confidence,
        "completed": result.completed,
        "stopped_reason": result.stopped_reason,
        "total_tokens_used": result.total_tokens_used,
        "llm_calls_count": result.llm_calls_count,
        "all_files_changed": result.all_files_changed,
        "all_commands_run": result.all_commands_run,
        "sub_results": [
            {
                "role": r.role,
                "task": r.task,
                "final_answer": r.result.final_answer,
                "stopped_reason": r.result.stopped_reason,
                "files_changed": r.result.files_changed,
                "error": r.error,
            }
            for r in result.sub_results
        ],
    }
    typer.echo(json.dumps(output, ensure_ascii=False, indent=2))


@skills_app.command("list")
def list_skills(
    project: str = typer.Option(".", "--project", help="Project root directory."),
    config: str = typer.Option("config/default.yaml", "--config", help="Path to config YAML."),
) -> None:
    from code_agent.skills import BUNDLED_SKILLS_DIR
    loaded = load_config(config)
    project_skills = (Path(project) / loaded.skills.directory).resolve()
    personal_skills = Path.home() / ".code-agent" / "skills"
    loader = SkillLoader(personal_skills, project_skills, BUNDLED_SKILLS_DIR)
    data = [{"name": item.name, "preview": item.preview} for item in loader.list_skills()]
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@skills_app.command("show")
def show_skill(
    name: str,
    project: str = typer.Option(".", "--project", help="Project root directory."),
    config: str = typer.Option("config/default.yaml", "--config", help="Path to config YAML."),
) -> None:
    from code_agent.skills import BUNDLED_SKILLS_DIR
    loaded = load_config(config)
    project_skills = (Path(project) / loaded.skills.directory).resolve()
    personal_skills = Path.home() / ".code-agent" / "skills"
    loader = SkillLoader(personal_skills, project_skills, BUNDLED_SKILLS_DIR)
    typer.echo(loader.read_skill(name))


@tools_app.command("list")
def list_tools() -> None:
    registry = build_tool_registry()
    typer.echo(json.dumps(registry.list_names(), ensure_ascii=False, indent=2))
