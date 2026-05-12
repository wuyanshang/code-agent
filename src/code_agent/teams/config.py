from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentRoleConfig(BaseModel):
    name: str
    role: str = ""
    tools: list[str] = Field(default_factory=list)
    system_prompt_extra: str = ""


class TeamConfig(BaseModel):
    mode: Literal["coordinate", "route"] = "coordinate"
    max_parallel: int = 5
    max_rounds: int = 2
    timeout_seconds: int = 300
    max_retries: int = 2
    max_context_messages: int = 40
    trim_keep_recent: int = 20
    max_total_tokens: int = 0
    checkpoint_dir: str = ".code-agent/checkpoints"
    roles: list[AgentRoleConfig] = Field(default_factory=list)
    planner_prompt: str = (
        "You are the lead planner for a research-oriented multi-agent team. "
        "Do not jump straight into implementation. First identify the goal, key unknowns, "
        "risks, and what evidence is needed. Prefer investigation and validation tasks over "
        "premature coding tasks. "
        "Return a JSON object with fields: "
        "framing (string), hypotheses (array of strings), tasks (array of {role, task}), "
        "open_questions (array of strings), should_implement (boolean). "
        "If you cannot reliably produce the full object, at minimum return a tasks array. "
        "Return JSON only."
    )
    critique_prompt: str = (
        "You are the critic for a research-oriented multi-agent team. "
        "Assess whether the current evidence is sufficient to support a conclusion. "
        "Return a JSON object with fields: "
        "assessment (string), gaps (array of strings), "
        "follow_up_tasks (array of {role, task}), ready_for_decision (boolean). "
        "Return JSON only."
    )
    judge_prompt: str = (
        "You are the final judge for a research-oriented multi-agent team. "
        "Based on the task, framing, sub-agent results, and critic feedback, decide the next step. "
        "Return a JSON object with fields: "
        "summary (string), decision (continue|implement|stop), confidence (low|medium|high), "
        "recommended_next_step (string), open_questions (array of strings), evidence (array of strings). "
        "Return JSON only."
    )
