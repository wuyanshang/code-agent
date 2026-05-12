from __future__ import annotations

from pathlib import Path

from code_agent.utils.paths import resolve_under


class PathGuard:
    def __init__(self, root: Path, ignore_patterns: list[str] | None = None) -> None:
        self.root = root.resolve()
        self.ignore_patterns = ignore_patterns or []

    def resolve(self, target: str | Path) -> Path:
        path = resolve_under(self.root, target)
        if not path.is_relative_to(self.root):
            raise ValueError(f"path escapes project root: {path}")
        return path

    def ensure_allowed(self, target: str | Path) -> Path:
        path = self.resolve(target)
        for part in path.parts:
            if part in self.ignore_patterns:
                raise ValueError(f"path is blocked by ignore pattern: {part}")
        return path
