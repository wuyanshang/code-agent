from __future__ import annotations

from pathlib import Path


def resolve_under(root: Path, target: str | Path) -> Path:
    path = Path(target)
    if not path.is_absolute():
        path = root / path
    return path.resolve()
