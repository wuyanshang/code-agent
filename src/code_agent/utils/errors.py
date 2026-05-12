from __future__ import annotations

import re


def format_tool_error_for_model(text: str, *, max_chars: int = 800) -> str:
    """
    将工具失败信息压缩为适合写进对话历史的短文本，避免整段 Traceback 占满上下文。
    完整信息仍应由调用处 logger.exception 记录。
    """
    s = (text or "").strip()
    if not s:
        return "tool failed"

    if "Traceback (most recent call last)" in s or re.search(r"File \"[^\"]+\"", s):
        first = s.splitlines()[0] if s else s
        if len(first) > max_chars:
            first = first[:max_chars] + "…"
        return first + "\n（完整堆栈已省略，请根据首行排查或查看日志。）"

    if len(s) > max_chars:
        return s[:max_chars] + "…"
    return s
