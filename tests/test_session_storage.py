from __future__ import annotations

from pathlib import Path

from code_agent.services.session_storage import (
    SESSION_FORMAT_VERSION,
    find_sessions_by_query,
    list_sessions,
    load_session_payload,
    prepare_messages_for_storage,
    save_session_payload,
    sessions_dir,
)


def test_sessions_dir_creates(tmp_path: Path) -> None:
    d = sessions_dir(tmp_path)
    assert d.is_dir()
    assert d.name == "sessions"


def test_save_list_load_roundtrip(tmp_path: Path) -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    sid = save_session_payload(
        tmp_path,
        session_id=None,
        title="t1",
        messages=msgs,
        model_name="m1",
        files_changed=["a.py"],
        commands_run=["git status"],
        selected_skill=None,
        plan_mode=False,
        tool_max_chars=10000,
    )
    assert len(sid) == 36
    rows = list_sessions(tmp_path)
    assert len(rows) == 1
    assert rows[0].title == "t1"
    data = load_session_payload(tmp_path, sid)
    assert data is not None
    assert data["format_version"] == SESSION_FORMAT_VERSION
    assert data["model_name"] == "m1"
    assert len(data["messages"]) == 2


def test_prepare_messages_truncates_tool(tmp_path: Path) -> None:
    msgs = [{"role": "tool", "tool_call_id": "1", "content": "x" * 5000}]
    out = prepare_messages_for_storage(msgs, 100)
    assert "截断" in out[0]["content"]


def test_find_sessions_by_query(tmp_path: Path) -> None:
    sid = save_session_payload(
        tmp_path,
        session_id=None,
        title="unique-apple-title",
        messages=[{"role": "user", "content": "u"}],
        model_name="",
        files_changed=[],
        commands_run=[],
        selected_skill=None,
        plan_mode=False,
        tool_max_chars=10000,
    )
    found = find_sessions_by_query(tmp_path, sid[:8])
    assert len(found) == 1
    found2 = find_sessions_by_query(tmp_path, "apple")
    assert len(found2) == 1
