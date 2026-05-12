from __future__ import annotations

import json
import logging
from typing import Any

from code_agent.config import AppConfig
from code_agent.llm.base import BaseLLMClient

logger = logging.getLogger(__name__)

COMPACT_SYSTEM_PROMPT = (
    "你是对话压缩助手，服务于编程 Agent。用户将提供一段「需要丢弃的」旧对话全文。"
    "请输出简洁的 Markdown 摘要，必须保留：\n"
    "1) 用户目标与约束；2) 出现过的文件路径与模块名；3) 已执行命令或工具结果的关键信息；"
    "4) 报错与根因；5) 尚未完成的事项。\n"
    "不要编造未出现的内容；不要输出与摘要无关的开场白。"
)


def split_messages_for_compact(
    messages: list[dict[str, Any]],
    keep_recent: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
    """
    与 apply_compact 一致：保留全部 system + 最近 keep_recent 条原消息；
    中间非 system 消息作为待摘要段。
    """
    if len(messages) <= 4 or len(messages) <= keep_recent:
        return None
    recent = messages[-keep_recent:]
    prefix = messages[:-keep_recent]
    system_msgs = [m for m in messages if m.get("role") == "system"]
    to_summarize = [m for m in prefix if m.get("role") != "system"]
    if not to_summarize:
        return None
    return (system_msgs, to_summarize, recent)


def _short(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len // 2] + "\n\n...[省略]...\n\n" + s[-max_len // 2 :]


def serialize_messages_for_summary(messages: list[dict[str, Any]], *, per_field_max: int = 12_000) -> str:
    """将消息转为可送入摘要模型的纯文本。"""
    lines: list[str] = []
    for i, m in enumerate(messages):
        role = m.get("role") or "unknown"
        if role == "user":
            lines.append(f"### User\n{_short(str(m.get('content', '')), per_field_max)}\n")
        elif role == "assistant":
            body = str(m.get("content") or "")
            tcs = m.get("tool_calls")
            if tcs:
                try:
                    body += "\n[tool_calls]\n" + json.dumps(tcs, ensure_ascii=False)[:8000]
                except (TypeError, ValueError):
                    body += "\n[tool_calls present]"
            lines.append(f"### Assistant\n{_short(body, per_field_max)}\n")
        elif role == "tool":
            tcid = m.get("tool_call_id") or ""
            c = str(m.get("content", ""))
            lines.append(f"### Tool ({tcid})\n{_short(c, per_field_max)}\n")
        else:
            lines.append(f"### {role}\n{_short(str(m), per_field_max)}\n")
    return "\n".join(lines)


def clamp_transcript(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = "\n\n...[中间已截断，仅摘要头尾]...\n\n"
    budget = max_chars - len(marker)
    if budget <= 0:
        return text[:max_chars]
    half = budget // 2
    return text[:half] + marker + text[-half:]


async def apply_compact_llm(
    messages: list[dict[str, Any]],
    llm: BaseLLMClient,
    config: AppConfig,
) -> tuple[list[dict[str, Any]], bool]:
    """
    调用模型生成摘要并重组消息列表。失败时由调用方回退 apply_compact。
    """
    ctx = config.context
    split = split_messages_for_compact(messages, ctx.compact_keep_recent)
    if split is None:
        return messages, False

    system_msgs, to_summarize, recent = split
    transcript = serialize_messages_for_summary(to_summarize)
    transcript = clamp_transcript(transcript, ctx.compact_source_max_chars)

    resp = await llm.chat(
        [
            {"role": "system", "content": COMPACT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "请将以下对话压缩为摘要（Markdown）。\n\n"
                    "---\n"
                    f"{transcript}\n"
                    "---"
                ),
            },
        ],
        tools=[],
    )
    summary = (resp.text or "").strip()
    if not summary:
        logger.warning("compact_llm: empty summary from model")
        return messages, False

    block = (
        "[对话智能压缩摘要 / 以下为模型对前文摘要，请在此继续]\n\n" + summary
    )
    new_msgs: list[dict[str, Any]] = list(system_msgs) + [{"role": "user", "content": block}] + list(recent)
    return new_msgs, True
