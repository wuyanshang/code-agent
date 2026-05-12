from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: json_safe(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value
