from __future__ import annotations

from dataclasses import asdict

from code_agent.schemas import ExecutionResult


def result_to_dict(result: ExecutionResult) -> dict:
    data = asdict(result)
    if data.get("pending_approval") is not None:
        data["pending_approval"] = asdict(result.pending_approval)
    return data
