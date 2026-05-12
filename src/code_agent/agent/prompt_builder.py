from __future__ import annotations

from pathlib import Path

from code_agent.agent.context import AgentContext
from code_agent.skills.loader import parse_frontmatter

AGENT_MD_NAME = "AGENT.md"
AGENT_LOCAL_MD_NAME = "AGENT.local.md"
RULES_DIR_NAME = "rules"


class PromptBuilder:
    def build_system_prompt(self, context: AgentContext) -> str:
        prompt = context.config.agent.system_prompt.strip()

        # 加载全局/项目/本地指令（类似 claude-code 的 CLAUDE.md 层级）
        memory_sections = self._load_memory_hierarchy(context.project_root)
        if memory_sections:
            prompt += "\n\n" + memory_sections

        if context.selected_skill:
            try:
                raw = context.skill_loader.read_skill(context.selected_skill)
                _meta, body = parse_frontmatter(raw)
                prompt += f"\n\n当前启用 skill [{context.selected_skill}]:\n{body.strip()}"
            except FileNotFoundError:
                pass

        skills_summary = self._build_skills_summary(context)
        if skills_summary:
            prompt += f"\n\n{skills_summary}"

        agents_summary = self._build_agents_summary(context)
        if agents_summary:
            prompt += f"\n\n{agents_summary}"

        prompt += "\n\n如果需要读取项目内容或修改文件，必须通过工具完成。"
        return prompt

    def _load_memory_hierarchy(self, project_root: Path) -> str:
        """按优先级从低到高加载多层指令文件，合并后注入系统 prompt。

        加载顺序（越后面优先级越高，放在 prompt 末尾让模型更关注）：
          1. ~/.code-agent/AGENT.md          — 用户全局约束，对所有项目生效
          2. {project}/.code-agent/AGENT.md  — 项目级约束
          3. {project}/AGENT.md              — 项目根约束
          4. {project}/.code-agent/rules/*.md — 项目规则碎片（按文件名排序）
          5. {project}/AGENT.local.md        — 本地私有覆盖（应加入 .gitignore）
        """
        candidates: list[tuple[str, Path]] = [
            ("用户全局指令", Path.home() / ".code-agent" / AGENT_MD_NAME),
            ("项目指令",     project_root / ".code-agent" / AGENT_MD_NAME),
            ("项目根指令",   project_root / AGENT_MD_NAME),
        ]

        # 项目规则碎片目录
        rules_dir = project_root / ".code-agent" / RULES_DIR_NAME
        if rules_dir.is_dir():
            for rule_file in sorted(rules_dir.glob("*.md")):
                candidates.append((f"规则[{rule_file.stem}]", rule_file))

        # 本地私有覆盖（gitignore 掉）
        candidates.append(("本地私有指令", project_root / AGENT_LOCAL_MD_NAME))

        parts: list[str] = []
        seen: set[Path] = set()
        for label, path in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            try:
                content = path.read_text(encoding="utf-8-sig").strip()
            except OSError:
                continue
            if content:
                parts.append(f"# {label}\n{content}")

        return "\n\n".join(parts)

    def _build_skills_summary(self, context: AgentContext) -> str:
        skills = context.skill_loader.list_skills()
        if not skills:
            return ""
        visible = [s for s in skills if not (s.meta and s.meta.disable_model_invocation)]
        if not visible:
            return ""
        lines = ["可用技能（你可以在合适的时机建议用户使用）:"]
        for s in visible:
            lines.append(f"  /{s.name} — {s.preview}")
        return "\n".join(lines)

    def _build_agents_summary(self, context: AgentContext) -> str:
        if context.agent_loader is None:
            return ""
        agents = context.agent_loader.list_agents()
        if not agents:
            return ""
        lines = [
            "可用子 Agent（你可以使用 delegate_agent 工具将子任务委派给它们）:",
        ]
        for a in agents:
            lines.append(f"  • {a.name} — {a.description}")
        return "\n".join(lines)
