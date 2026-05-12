from __future__ import annotations

from code_agent.utils.context_budget import (
    apply_compact,
    estimate_messages_tokens,
    truncate_tool_content,
    truncate_tool_messages_in_history,
)


def test_estimate_messages_tokens_basic() -> None:
    messages = [
        {"role": "system", "content": "a" * 300},
        {"role": "user", "content": "b" * 300},
    ]
    est = estimate_messages_tokens(messages)
    assert est == 200  # 600 chars / 3


def test_truncate_tool_content() -> None:
    long = "x" * 100
    out = truncate_tool_content(long, 20)
    assert len(out) < len(long)
    assert "截断" in out


def test_truncate_tool_messages_in_history() -> None:
    messages = [
        {"role": "tool", "tool_call_id": "1", "content": "y" * 5000},
        {"role": "assistant", "content": "ok"},
    ]
    n = truncate_tool_messages_in_history(messages, 100)
    assert n == 1
    assert "截断" in messages[0]["content"]


def test_apply_compact_short() -> None:
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    new_msgs, changed = apply_compact(msgs)
    assert changed is False
    assert new_msgs is msgs


def test_apply_compact_long() -> None:
    msgs = [{"role": "system", "content": "s"}]
    for i in range(10):
        msgs.append({"role": "user", "content": f"u{i}"})
    new_msgs, changed = apply_compact(msgs, keep_recent=3)
    assert changed is True
    assert any("压缩" in str(m.get("content", "")) for m in new_msgs)
