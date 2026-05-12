from pathlib import Path

import pytest

from code_agent.safety.path_guard import PathGuard


def test_path_guard_blocks_outside_root(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    with pytest.raises(ValueError):
        guard.ensure_allowed("../outside.txt")
