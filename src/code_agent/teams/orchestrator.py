from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from code_agent.config import AppConfig
from code_agent.llm.base import BaseLLMClient
from code_agent.teams.config import AgentRoleConfig, TeamConfig
from code_agent.teams.sub_agent import SubAgent, SubAgentResult
from code_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class TeamResult:
    task: str
    framing: str = ""
    hypotheses: list[str] = field(default_factory=list)
    sub_results: list[SubAgentResult] = field(default_factory=list)
    summary: str = ""
    decision: str = "continue"
    confidence: str = "low"
    recommended_next_step: str = ""
    evidence: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    all_files_changed: list[str] = field(default_factory=list)
    all_commands_run: list[str] = field(default_factory=list)
    # 成本追踪
    total_tokens_used: int = 0
    llm_calls_count: int = 0
    # 执行状态
    completed: bool = True
    stopped_reason: str = "completed"  # completed, timeout, token_limit_exceeded, error


class TeamOrchestrator:
    def __init__(
        self,
        team_config: TeamConfig,
        app_config: AppConfig,
        llm_client: BaseLLMClient,
        tool_registry: ToolRegistry,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.team_config = team_config
        self.app_config = app_config
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.progress_callback = progress_callback
        self._roles: dict[str, AgentRoleConfig] = {r.name: r for r in team_config.roles}
        self._total_tokens = 0
        self._llm_calls = 0

    async def run(self, task: str, project_root: str | Path, checkpoint_path: Path | None = None) -> TeamResult:
        """运行team任务，支持超时控制和checkpoint恢复"""
        try:
            return await asyncio.wait_for(
                self._run_internal(task, project_root, checkpoint_path),
                timeout=self.team_config.timeout_seconds if self.team_config.timeout_seconds > 0 else None
            )
        except asyncio.TimeoutError:
            logger.warning("team execution timeout after %s seconds", self.team_config.timeout_seconds)
            return TeamResult(
                task=task,
                summary=f"执行超时（{self.team_config.timeout_seconds}秒）",
                completed=False,
                stopped_reason="timeout",
                total_tokens_used=self._total_tokens,
                llm_calls_count=self._llm_calls,
            )

    async def _run_internal(self, task: str, project_root: str | Path, checkpoint_path: Path | None = None) -> TeamResult:
        root = Path(project_root).resolve()

        # 尝试从checkpoint恢复
        if checkpoint_path and checkpoint_path.exists():
            self._emit_progress("从checkpoint恢复...")
            checkpoint_data = self._load_checkpoint(checkpoint_path)
            if checkpoint_data:
                return await self._resume_from_checkpoint(checkpoint_data, root)

        self._emit_progress("开始任务分析...")
        framing = await self._frame(task)
        self._emit_progress(f"任务分解完成，生成{len(framing['tasks'])}个子任务")

        collected_results: list[SubAgentResult] = []
        current_tasks = framing["tasks"]
        max_rounds = max(1, self.team_config.max_rounds)
        critique: dict[str, Any] = {
            "assessment": "",
            "gaps": list(framing["open_questions"]),
            "follow_up_tasks": [],
            "ready_for_decision": bool(framing["should_implement"]),
        }

        for round_index in range(max_rounds):
            if not current_tasks:
                break

            # 检查token限制
            if self._check_token_limit():
                return self._build_result_with_limit_exceeded(task, framing, collected_results, critique)

            self._emit_progress(f"执行第{round_index + 1}轮，{len(current_tasks)}个子任务...")
            round_results = await self._run_round(current_tasks, root)
            collected_results.extend(round_results)

            # 保存checkpoint
            self._save_checkpoint(task, root, framing, collected_results, critique, round_index)

            self._emit_progress(f"第{round_index + 1}轮完成，评估结果...")
            critique = await self._critique(task, framing, collected_results)
            if critique["ready_for_decision"]:
                break

            current_tasks = critique["follow_up_tasks"]
            if not current_tasks:
                break

            logger.info(
                "team research round %s requested %s follow-up tasks",
                round_index + 1,
                len(current_tasks),
            )

        self._emit_progress("生成最终决策...")
        judgement = await self._judge(task, framing, collected_results, critique)
        all_files = sorted(set(f for r in collected_results for f in r.result.files_changed))
        all_cmds = [c for r in collected_results for c in r.result.commands_run]

        return TeamResult(
            task=task,
            framing=framing["framing"],
            hypotheses=framing["hypotheses"],
            sub_results=collected_results,
            summary=judgement["summary"],
            decision=judgement["decision"],
            confidence=judgement["confidence"],
            recommended_next_step=judgement["recommended_next_step"],
            evidence=judgement["evidence"],
            open_questions=judgement["open_questions"],
            all_files_changed=all_files,
            all_commands_run=all_cmds,
            total_tokens_used=self._total_tokens,
            llm_calls_count=self._llm_calls,
            completed=True,
            stopped_reason="completed",
        )

    async def _frame(self, task: str) -> dict[str, Any]:
        role_list = ", ".join(self._roles.keys()) if self._roles else "assistant"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.team_config.planner_prompt},
            {
                "role": "user",
                "content": (
                    f"Available roles: {role_list}\n\n"
                    f"User task:\n{task}\n\n"
                    "Return JSON only."
                ),
            },
        ]
        response = await self.llm_client.chat(messages, tools=[])
        self._track_llm_call(response)
        return _parse_framing(response.text, list(self._roles.keys()))

    async def _run_round(self, plan: list[dict[str, str]], root: Path) -> list[SubAgentResult]:
        logger.info("team round: %s sub-tasks", len(plan))
        semaphore = asyncio.Semaphore(self.team_config.max_parallel)
        sub_agents_tasks = []

        for item in plan:
            role_name = item["role"]
            sub_task = item["task"]
            role_config = self._resolve_role(role_name)
            agent = SubAgent(
                role_config,
                self.app_config,
                self.llm_client,
                self.tool_registry,
                max_context_messages=self.team_config.max_context_messages,
                trim_keep_recent=self.team_config.trim_keep_recent,
            )

            async def _run_with_retry(a: SubAgent = agent, t: str = sub_task, r: str = role_name) -> SubAgentResult:
                async with semaphore:
                    for attempt in range(self.team_config.max_retries + 1):
                        try:
                            result = await a.run(t, root)
                            # 如果成功或者是最后一次尝试，返回结果
                            if result.error is None or attempt == self.team_config.max_retries:
                                if attempt > 0:
                                    logger.info("sub-agent [%s] succeeded on retry %s", r, attempt)
                                return result
                            # 失败但还有重试机会
                            logger.warning("sub-agent [%s] failed (attempt %s/%s): %s",
                                         r, attempt + 1, self.team_config.max_retries + 1, result.error)
                            await asyncio.sleep(1)  # 简单的退避策略
                        except Exception as exc:
                            if attempt == self.team_config.max_retries:
                                logger.error("sub-agent [%s] failed after %s retries: %s", r, attempt + 1, exc)
                                return SubAgentResult(
                                    role=r,
                                    task=t,
                                    result=_error_execution_result(str(exc)),
                                    error=str(exc),
                                )
                            logger.warning("sub-agent [%s] exception (attempt %s/%s): %s",
                                         r, attempt + 1, self.team_config.max_retries + 1, exc)
                            await asyncio.sleep(1)
                    # 不应该到达这里
                    return SubAgentResult(
                        role=r,
                        task=t,
                        result=_error_execution_result("Max retries exceeded"),
                        error="Max retries exceeded",
                    )

            sub_agents_tasks.append(_run_with_retry())

        sub_results = await asyncio.gather(*sub_agents_tasks, return_exceptions=True)
        processed: list[SubAgentResult] = []
        for result in sub_results:
            if isinstance(result, Exception):
                processed.append(
                    SubAgentResult(
                        role="unknown",
                        task="",
                        result=_error_execution_result(str(result)),
                        error=str(result),
                    )
                )
            else:
                processed.append(result)
        return processed

    async def _critique(
        self,
        task: str,
        framing: dict[str, Any],
        results: list[SubAgentResult],
    ) -> dict[str, Any]:
        parts = []
        for r in results:
            status = "completed" if r.result.stopped_reason == "completed" else r.result.stopped_reason
            parts.append(f"[{r.role}] ({status}): {r.result.final_answer[:800]}")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.team_config.critique_prompt},
            {
                "role": "user",
                "content": (
                    f"Task: {task}\n\n"
                    f"Framing: {framing['framing']}\n\n"
                    f"Hypotheses: {json.dumps(framing['hypotheses'], ensure_ascii=False)}\n\n"
                    f"Current results:\n" + "\n".join(parts) + "\n\n"
                    "Return JSON only."
                ),
            },
        ]
        response = await self.llm_client.chat(messages, tools=[])
        self._track_llm_call(response)
        return _parse_critique(response.text, list(self._roles.keys()))

    async def _judge(
        self,
        task: str,
        framing: dict[str, Any],
        results: list[SubAgentResult],
        critique: dict[str, Any],
    ) -> dict[str, Any]:
        parts = []
        evidence: list[str] = []
        for r in results:
            status = "completed" if r.result.stopped_reason == "completed" else r.result.stopped_reason
            snippet = r.result.final_answer[:800]
            parts.append(f"[{r.role}] ({status}): {snippet}")
            if snippet:
                evidence.append(f"{r.role}: {snippet[:200]}")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.team_config.judge_prompt},
            {
                "role": "user",
                "content": (
                    f"Task: {task}\n\n"
                    f"Framing: {framing['framing']}\n\n"
                    f"Open questions: {json.dumps(framing['open_questions'], ensure_ascii=False)}\n\n"
                    f"Critique assessment: {critique['assessment']}\n"
                    f"Critique gaps: {json.dumps(critique['gaps'], ensure_ascii=False)}\n\n"
                    f"Results:\n" + "\n".join(parts) + "\n\n"
                    "Return JSON only."
                ),
            },
        ]
        response = await self.llm_client.chat(messages, tools=[])
        self._track_llm_call(response)
        return _parse_judgement(response.text, evidence, critique.get("gaps") or framing["open_questions"])

    def _resolve_role(self, name: str) -> AgentRoleConfig:
        if name in self._roles:
            return self._roles[name]
        logger.warning("unknown role '%s', creating default", name)
        return AgentRoleConfig(name=name, role=f"General assistant focused on {name}")

    def _emit_progress(self, message: str) -> None:
        """发送进度消息"""
        if self.progress_callback:
            self.progress_callback(message)
        logger.info(message)

    def _track_llm_call(self, response: Any) -> None:
        """追踪LLM调用的token使用"""
        self._llm_calls += 1
        # 尝试从response中获取token信息（如果LLM客户端提供）
        if hasattr(response, 'usage') and response.usage:
            if hasattr(response.usage, 'total_tokens'):
                self._total_tokens += response.usage.total_tokens
        # 如果没有usage信息，使用简单估算（1 token ≈ 4 chars）
        elif hasattr(response, 'text') and response.text:
            estimated_tokens = len(response.text) // 4
            self._total_tokens += estimated_tokens

    def _check_token_limit(self) -> bool:
        """检查是否超过token限制"""
        if self.team_config.max_total_tokens > 0:
            if self._total_tokens >= self.team_config.max_total_tokens:
                logger.warning("token limit exceeded: %s >= %s",
                             self._total_tokens, self.team_config.max_total_tokens)
                return True
        return False

    def _build_result_with_limit_exceeded(
        self,
        task: str,
        framing: dict[str, Any],
        collected_results: list[SubAgentResult],
        critique: dict[str, Any],
    ) -> TeamResult:
        """构建token限制超出时的结果"""
        all_files = sorted(set(f for r in collected_results for f in r.result.files_changed))
        all_cmds = [c for r in collected_results for c in r.result.commands_run]
        return TeamResult(
            task=task,
            framing=framing["framing"],
            hypotheses=framing["hypotheses"],
            sub_results=collected_results,
            summary=f"Token使用量超过限制（{self._total_tokens}/{self.team_config.max_total_tokens}），任务提前终止",
            decision="stop",
            confidence="low",
            recommended_next_step="增加token限制或简化任务",
            evidence=[],
            open_questions=critique.get("gaps", []),
            all_files_changed=all_files,
            all_commands_run=all_cmds,
            total_tokens_used=self._total_tokens,
            llm_calls_count=self._llm_calls,
            completed=False,
            stopped_reason="token_limit_exceeded",
        )

    def _save_checkpoint(
        self,
        task: str,
        root: Path,
        framing: dict[str, Any],
        collected_results: list[SubAgentResult],
        critique: dict[str, Any],
        round_index: int,
    ) -> None:
        """保存checkpoint到磁盘"""
        try:
            checkpoint_dir = root / self.team_config.checkpoint_dir
            checkpoint_dir.mkdir(parents=True, exist_ok=True)

            checkpoint_file = checkpoint_dir / f"team_checkpoint_{round_index}.json"
            checkpoint_data = {
                "task": task,
                "framing": framing,
                "collected_results": [
                    {
                        "role": r.role,
                        "task": r.task,
                        "final_answer": r.result.final_answer,
                        "stopped_reason": r.result.stopped_reason,
                        "files_changed": r.result.files_changed,
                        "commands_run": r.result.commands_run,
                        "error": r.error,
                    }
                    for r in collected_results
                ],
                "critique": critique,
                "round_index": round_index,
                "total_tokens": self._total_tokens,
                "llm_calls": self._llm_calls,
            }

            checkpoint_file.write_text(json.dumps(checkpoint_data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("checkpoint saved to %s", checkpoint_file)
        except Exception as exc:
            logger.warning("failed to save checkpoint: %s", exc)

    def _load_checkpoint(self, checkpoint_path: Path) -> dict[str, Any] | None:
        """从磁盘加载checkpoint"""
        try:
            data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            logger.info("checkpoint loaded from %s", checkpoint_path)
            return data
        except Exception as exc:
            logger.warning("failed to load checkpoint: %s", exc)
            return None

    async def _resume_from_checkpoint(self, checkpoint_data: dict[str, Any], root: Path) -> TeamResult:
        """从checkpoint恢复执行"""
        task = checkpoint_data["task"]
        framing = checkpoint_data["framing"]
        round_index = checkpoint_data["round_index"]

        # 恢复token计数
        self._total_tokens = checkpoint_data.get("total_tokens", 0)
        self._llm_calls = checkpoint_data.get("llm_calls", 0)

        # 重建SubAgentResult（简化版，不包含完整的ExecutionResult）
        from code_agent.schemas import ExecutionResult
        collected_results = [
            SubAgentResult(
                role=r["role"],
                task=r["task"],
                result=ExecutionResult(
                    final_answer=r["final_answer"],
                    stopped_reason=r["stopped_reason"],
                    files_changed=r["files_changed"],
                    commands_run=r["commands_run"],
                ),
                error=r.get("error"),
            )
            for r in checkpoint_data["collected_results"]
        ]

        critique = checkpoint_data["critique"]

        self._emit_progress(f"从第{round_index + 1}轮恢复...")

        # 继续执行后续轮次
        max_rounds = max(1, self.team_config.max_rounds)
        for next_round in range(round_index + 1, max_rounds):
            current_tasks = critique.get("follow_up_tasks", [])
            if not current_tasks or critique.get("ready_for_decision"):
                break

            if self._check_token_limit():
                return self._build_result_with_limit_exceeded(task, framing, collected_results, critique)

            self._emit_progress(f"执行第{next_round + 1}轮...")
            round_results = await self._run_round(current_tasks, root)
            collected_results.extend(round_results)

            self._save_checkpoint(task, root, framing, collected_results, critique, next_round)

            critique = await self._critique(task, framing, collected_results)
            if critique["ready_for_decision"]:
                break

        self._emit_progress("生成最终决策...")
        judgement = await self._judge(task, framing, collected_results, critique)
        all_files = sorted(set(f for r in collected_results for f in r.result.files_changed))
        all_cmds = [c for r in collected_results for c in r.result.commands_run]

        return TeamResult(
            task=task,
            framing=framing["framing"],
            hypotheses=framing["hypotheses"],
            sub_results=collected_results,
            summary=judgement["summary"],
            decision=judgement["decision"],
            confidence=judgement["confidence"],
            recommended_next_step=judgement["recommended_next_step"],
            evidence=judgement["evidence"],
            open_questions=judgement["open_questions"],
            all_files_changed=all_files,
            all_commands_run=all_cmds,
            total_tokens_used=self._total_tokens,
            llm_calls_count=self._llm_calls,
            completed=True,
            stopped_reason="completed",
        )



def _clean_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _safe_json_loads(text: str) -> Any | None:
    cleaned = _clean_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    for open_char, close_char in (("{", "}"), ("[", "]")):
        start = cleaned.find(open_char)
        end = cleaned.rfind(close_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _normalize_tasks(raw: Any, known_roles: list[str]) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []

    tasks: list[dict[str, str]] = []
    fallback_role = known_roles[0] if known_roles else "assistant"
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or fallback_role).strip() or fallback_role
        task = str(item.get("task") or "").strip()
        if task:
            tasks.append({"role": role, "task": task})
    return tasks


def _parse_framing(text: str, known_roles: list[str]) -> dict[str, Any]:
    parsed = _safe_json_loads(text)

    if isinstance(parsed, list):
        tasks = _normalize_tasks(parsed, known_roles)
        return {
            "framing": "",
            "hypotheses": [],
            "tasks": tasks or [{"role": known_roles[0] if known_roles else "assistant", "task": text}],
            "open_questions": [],
            "should_implement": False,
        }

    if isinstance(parsed, dict):
        tasks = _normalize_tasks(parsed.get("tasks"), known_roles)
        return {
            "framing": str(parsed.get("framing") or "").strip(),
            "hypotheses": _coerce_string_list(parsed.get("hypotheses")),
            "tasks": tasks or [{"role": known_roles[0] if known_roles else "assistant", "task": text}],
            "open_questions": _coerce_string_list(parsed.get("open_questions")),
            "should_implement": bool(parsed.get("should_implement", False)),
        }

    return {
        "framing": "",
        "hypotheses": [],
        "tasks": [{"role": known_roles[0] if known_roles else "assistant", "task": text}],
        "open_questions": [],
        "should_implement": False,
    }


def _parse_critique(text: str, known_roles: list[str]) -> dict[str, Any]:
    parsed = _safe_json_loads(text)
    if isinstance(parsed, dict):
        return {
            "assessment": str(parsed.get("assessment") or "").strip(),
            "gaps": _coerce_string_list(parsed.get("gaps")),
            "follow_up_tasks": _normalize_tasks(parsed.get("follow_up_tasks"), known_roles),
            "ready_for_decision": bool(parsed.get("ready_for_decision", False)),
        }
    return {
        "assessment": text.strip(),
        "gaps": [],
        "follow_up_tasks": [],
        "ready_for_decision": True,
    }


def _parse_judgement(
    text: str,
    fallback_evidence: list[str],
    fallback_open_questions: list[str],
) -> dict[str, Any]:
    parsed = _safe_json_loads(text)
    if isinstance(parsed, dict):
        return {
            "summary": str(parsed.get("summary") or text).strip(),
            "decision": str(parsed.get("decision") or "continue").strip() or "continue",
            "confidence": str(parsed.get("confidence") or "medium").strip() or "medium",
            "recommended_next_step": str(parsed.get("recommended_next_step") or "").strip(),
            "open_questions": _coerce_string_list(parsed.get("open_questions")) or list(fallback_open_questions),
            "evidence": _coerce_string_list(parsed.get("evidence")) or list(fallback_evidence),
        }
    return {
        "summary": text.strip(),
        "decision": "continue",
        "confidence": "medium",
        "recommended_next_step": "",
        "open_questions": list(fallback_open_questions),
        "evidence": list(fallback_evidence),
    }


def _coerce_string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _parse_plan(text: str, known_roles: list[str]) -> list[dict[str, str]]:
    return _parse_framing(text, known_roles)["tasks"]


def _error_execution_result(error: str) -> Any:
    from code_agent.schemas import ExecutionResult

    return ExecutionResult(final_answer=f"Execution error: {error}", stopped_reason="error")
