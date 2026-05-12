"""模型摘要压缩与序列化。"""

import asyncio

from code_agent.config import AppConfig
from code_agent.llm.mock import MockLLMClient
from code_agent.utils.compact_llm import (
    apply_compact_llm,
    clamp_transcript,
    serialize_messages_for_summary,
    split_messages_for_compact,
)
from code_agent.utils.context_budget import apply_compact


def test_split_too_short() -> None:
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert split_messages_for_compact(msgs, keep_recent=6) is None


def test_split_ok() -> None:
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(10):
        msgs.append({"role": "user", "content": f"u{i}"})
    sp = split_messages_for_compact(msgs, keep_recent=3)
    assert sp is not None
    _sys, mid, recent = sp
    assert len(recent) == 3
    assert len(mid) == 7


def test_serialize_roundtrip() -> None:
    s = serialize_messages_for_summary(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "result"},
        ]
    )
    assert "User" in s and "Assistant" in s and "Tool" in s


def test_clamp_transcript() -> None:
    long = "x" * 5000
    out = clamp_transcript(long, 200)
    assert len(out) <= 220
    assert "截断" in out


def test_apply_compact_llm_mock() -> None:
    cfg = AppConfig()
    msgs: list[dict] = [{"role": "system", "content": "s"}]
    for i in range(10):
        msgs.append({"role": "user", "content": f"msg{i}"})
    llm = MockLLMClient()
    new_msgs, ok = asyncio.run(apply_compact_llm(msgs, llm, cfg))
    assert ok
    assert any("Mock 摘要" in str(m.get("content", "")) for m in new_msgs)
    assert len(new_msgs) < len(msgs)


def test_apply_compact_fallback_same_keep_recent() -> None:
    msgs = [{"role": "system", "content": "s"}]
    for i in range(10):
        msgs.append({"role": "user", "content": f"u{i}"})
    new_msgs, changed = apply_compact(msgs, keep_recent=3)
    assert changed
    sp = split_messages_for_compact(msgs, keep_recent=3)
    assert sp is not None
    assert len(sp[2]) == 3
