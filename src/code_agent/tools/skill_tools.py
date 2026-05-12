from __future__ import annotations

from typing import Any

from code_agent.schemas import ToolResult
from code_agent.skills.loader import parse_frontmatter, render_skill_content
from code_agent.tools.base import BaseTool


class ListSkillsTool(BaseTool):
    name = "list_skills"
    description = "列出可用 skills，返回名称和描述。"
    parameters_schema = {"type": "object", "properties": {}}

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        skills = context.skill_loader.list_skills()
        if not skills:
            return ToolResult(ok=True, content="暂无可用 skill。")
        lines = []
        for item in skills:
            flags = []
            if item.meta and item.meta.disable_model_invocation:
                flags.append("仅用户可调用")
            if item.meta and not item.meta.user_invocable:
                flags.append("仅LLM可调用")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"/{item.name} — {item.preview}{flag_str}")
        return ToolResult(ok=True, content="\n".join(lines))


class ReadSkillTool(BaseTool):
    name = "read_skill"
    description = "读取某个 skill 的完整内容（包括 frontmatter）。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "技能名称"},
        },
        "required": ["name"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        try:
            text = context.skill_loader.read_skill(arguments["name"])
        except FileNotFoundError:
            return ToolResult(ok=False, content="", error=f"skill not found: {arguments['name']}")
        return ToolResult(ok=True, content=text)


class InvokeSkillTool(BaseTool):
    name = "invoke_skill"
    description = (
        "激活一个 skill 并返回其指令内容。"
        "当你发现用户的任务适合某个 skill 时，调用此工具加载该 skill 的指令，"
        "然后按照返回的指令执行。支持传入参数（会替换 $ARGUMENTS 占位符）。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "技能名称"},
            "arguments": {"type": "string", "description": "传给技能的参数（可选）", "default": ""},
        },
        "required": ["name"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        name = arguments["name"]
        skill_args = arguments.get("arguments", "")

        try:
            meta, body = context.skill_loader.read_skill_parsed(name)
        except FileNotFoundError:
            return ToolResult(ok=False, content="", error=f"skill not found: {name}")

        if meta and meta.disable_model_invocation:
            return ToolResult(
                ok=False, content="",
                error=f"skill '{name}' 仅支持用户手动调用 (/{name})，LLM 不可自动触发。",
            )

        rendered = render_skill_content(body, skill_args)
        header = f"[skill: {meta.name if meta and meta.name else name}]"
        if meta and meta.description:
            header += f" {meta.description}"

        return ToolResult(ok=True, content=f"{header}\n\n{rendered}")
