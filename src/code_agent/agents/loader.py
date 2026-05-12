from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BUNDLED_AGENTS_DIR = Path(__file__).resolve().parent / "bundled"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(slots=True)
class AgentDef:
    name: str
    description: str = ""
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    model: str = ""
    max_turns: int = 8
    skills: list[str] = field(default_factory=list)
    system_prompt: str = ""
    source: str = ""


def parse_agent_file(text: str) -> AgentDef | None:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None

    raw_yaml = m.group(1)
    body = text[m.end():].strip()

    try:
        data = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict) or "name" not in data:
        return None

    tools_raw = data.get("tools", "")
    if isinstance(tools_raw, str):
        tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
    elif isinstance(tools_raw, list):
        tools = [str(t).strip() for t in tools_raw]
    else:
        tools = []

    disallowed_raw = data.get("disallowedTools") or data.get("disallowed_tools") or ""
    if isinstance(disallowed_raw, str):
        disallowed = [t.strip() for t in disallowed_raw.split(",") if t.strip()]
    elif isinstance(disallowed_raw, list):
        disallowed = [str(t).strip() for t in disallowed_raw]
    else:
        disallowed = []

    skills_raw = data.get("skills", [])
    if isinstance(skills_raw, str):
        skills_list = [s.strip() for s in skills_raw.split(",") if s.strip()]
    elif isinstance(skills_raw, list):
        skills_list = [str(s).strip() for s in skills_raw]
    else:
        skills_list = []

    return AgentDef(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        tools=tools,
        disallowed_tools=disallowed,
        model=str(data.get("model", "")),
        max_turns=int(data.get("maxTurns") or data.get("max_turns") or 8),
        skills=skills_list,
        system_prompt=body,
    )


class AgentLoader:
    def __init__(self, *agent_dirs: Path) -> None:
        self.agent_dirs = list(agent_dirs)

    def list_agents(self) -> list[AgentDef]:
        seen: set[str] = set()
        agents: list[AgentDef] = []
        for d in self.agent_dirs:
            if not d.exists():
                continue
            for f in sorted(d.iterdir()):
                if not f.is_file() or f.suffix.lower() != ".md":
                    continue
                text = f.read_text(encoding="utf-8-sig")
                agent_def = parse_agent_file(text)
                if agent_def and agent_def.name not in seen:
                    agent_def.source = str(d)
                    seen.add(agent_def.name)
                    agents.append(agent_def)
        return agents

    def get_agent(self, name: str) -> AgentDef | None:
        for agent in self.list_agents():
            if agent.name == name:
                return agent
        return None
