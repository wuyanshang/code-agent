from __future__ import annotations

import json
from typing import Any


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """粗略估算对话占用 token 数（中英混合：约每 3 个字符 1 token）。"""
    total_chars = 0
    for m in messages:
        total_chars += _message_char_weight(m)
    return max(1, total_chars // 3)


def _message_char_weight(m: dict[str, Any]) -> int:
    c = 0
    content = m.get("content")
    if content:
        c += len(str(content))
    tool_calls = m.get("tool_calls")
    if tool_calls:
        c += len(json.dumps(tool_calls, ensure_ascii=False))
    return c


def truncate_tool_content(content: str, max_chars: int) -> str:
    """截断单条 tool 返回内容，避免历史里堆满长文本。"""
    if max_chars <= 0 or len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n...[内容已截断，可在配置中调整 context.tool_message_max_chars]"


def truncate_tool_messages_in_history(
    messages: list[dict[str, Any]],
    max_chars: int,
) -> int:
    """
    就地截断所有 role=tool 的 content。返回被截断的条数。
    """
    n = 0
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content")
        if not isinstance(content, str):
            continue
        if len(content) > max_chars:
            m["content"] = truncate_tool_content(content, max_chars)
            n += 1
    return n


def apply_compact(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = 6,
    placeholder: str = "[之前的对话已被自动压缩，请基于最近上下文继续]",
) -> tuple[list[dict[str, Any]], bool]:
    """
    保留全部 system 消息 + 最近 keep_recent 条，中间插入占位 user。
    返回 (新列表, 是否发生了压缩)。
    """
    if len(messages) <= 4:
        return messages, False
    system_msgs = [m for m in messages if m.get("role") == "system"]
    recent = messages[-keep_recent:]
    new_msgs: list[dict[str, Any]] = list(system_msgs)
    new_msgs.append({"role": "user", "content": placeholder})
    new_msgs.extend(recent)
    return new_msgs, True
