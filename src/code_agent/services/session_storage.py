from __future__ import annotations

import copy
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code_agent.utils.context_budget import truncate_tool_messages_in_history

logger = logging.getLogger(__name__)

SESSION_FORMAT_VERSION = 1
SESSIONS_SUBDIR = Path(".code-agent") / "sessions"


def sessions_dir(project_root: Path) -> Path:
    d = (project_root / SESSIONS_SUBDIR).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(slots=True)
class SessionSummary:
    session_id: str
    title: str
    updated_at: str
    message_count: int
    path: Path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_title_from_messages(messages: list[dict[str, Any]]) -> str:
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            t = m["content"].strip().replace("\n", " ")
            return (t[:80] + "…") if len(t) > 80 else t or "未命名会话"
    return "未命名会话"


def prepare_messages_for_storage(
    messages: list[dict[str, Any]],
    tool_max_chars: int,
) -> list[dict[str, Any]]:
    out = copy.deepcopy(messages)
    truncate_tool_messages_in_history(out, tool_max_chars)
    return out


def list_sessions(project_root: Path, limit: int = 40) -> list[SessionSummary]:
    d = sessions_dir(project_root)
    summaries: list[SessionSummary] = []
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if len(summaries) >= limit:
            break
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("skip session file %s: %s", p, exc)
            continue
        if raw.get("format_version") != SESSION_FORMAT_VERSION:
            continue
        sid = raw.get("id") or p.stem
        summaries.append(
            SessionSummary(
                session_id=sid,
                title=raw.get("title") or "(无标题)",
                updated_at=raw.get("updated_at") or "",
                message_count=len(raw.get("messages") or []),
                path=p,
            )
        )
    return summaries


def find_sessions_by_query(project_root: Path, query: str) -> list[SessionSummary]:
    q = query.strip().lower()
    if not q:
        return []
    all_s = list_sessions(project_root, limit=200)
    matches = [
        s
        for s in all_s
        if s.session_id.lower().startswith(q) or q in s.session_id.lower() or q in s.title.lower()
    ]
    return matches


def load_session_payload(project_root: Path, session_id: str) -> dict[str, Any] | None:
    """按完整 id 或文件名 stem 精确匹配。"""
    d = sessions_dir(project_root)
    path = d / f"{session_id}.json"
    if not path.is_file():
        for p in d.glob("*.json"):
            if p.stem == session_id:
                path = p
                break
        else:
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_session_payload(
    project_root: Path,
    *,
    session_id: str | None,
    title: str | None,
    messages: list[dict[str, Any]],
    model_name: str,
    files_changed: list[str],
    commands_run: list[str],
    selected_skill: str | None,
    plan_mode: bool,
    tool_max_chars: int,
) -> str:
    d = sessions_dir(project_root)
    sid = session_id or str(uuid.uuid4())
    path = d / f"{sid}.json"
    now = _utc_now_iso()
    created = now
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            created = old.get("created_at") or now
        except (OSError, json.JSONDecodeError):
            pass
    final_title = title or _default_title_from_messages(messages)
    payload: dict[str, Any] = {
        "format_version": SESSION_FORMAT_VERSION,
        "id": sid,
        "title": final_title,
        "created_at": created,
        "updated_at": now,
        "project_root": str(project_root.resolve()),
        "model_name": model_name,
        "messages": prepare_messages_for_storage(messages, tool_max_chars),
        "files_changed": files_changed,
        "commands_run": commands_run,
        "selected_skill": selected_skill,
        "plan_mode": plan_mode,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return sid


def delete_session(project_root: Path, query: str) -> bool:
    matches = find_sessions_by_query(project_root, query)
    if len(matches) != 1:
        return False
    try:
        matches[0].path.unlink()
        return True
    except OSError:
        return False
