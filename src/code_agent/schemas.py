from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class CommandDecision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@runtime_checkable
class ApprovalProtocol(Protocol):
    def is_approved(self, command: str, reason: str) -> bool: ...


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_response: Any | None = None
    finish_reason: str | None = None


@dataclass(slots=True)
class ToolResult:
    ok: bool
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class PendingApproval:
    command: str
    reason: str
    decision: CommandDecision = CommandDecision.REQUIRE_APPROVAL


@dataclass(slots=True)
class ExecutionResult:
    final_answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    diff_preview: str = ""
    commands_run: list[str] = field(default_factory=list)
    skill_used: str | None = None
    stopped_reason: str | None = None
    pending_approval: PendingApproval | None = None
