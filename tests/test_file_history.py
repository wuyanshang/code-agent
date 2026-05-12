from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from code_agent.services.file_history import FileHistoryManager


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def file_history(temp_dir):
    backup_root = temp_dir / "backups"
    return FileHistoryManager(backup_root, "test-session")


def test_create_backup_new_file(file_history, temp_dir):
    """测试备份不存在的文件"""
    file_path = temp_dir / "new_file.txt"
    backup = file_history.create_backup(file_path, "new_file.txt")

    assert backup.backup_path is None
    assert backup.version == 1
    assert backup.original_path == "new_file.txt"


def test_create_backup_existing_file(file_history, temp_dir):
    """测试备份已存在的文件"""
    file_path = temp_dir / "existing.txt"
    file_path.write_text("original content", encoding="utf-8")

    backup = file_history.create_backup(file_path, "existing.txt")

    assert backup.backup_path is not None
    assert backup.backup_path.exists()
    assert backup.backup_path.read_text(encoding="utf-8") == "original content"
    assert backup.version == 1


def test_track_file_edit(file_history, temp_dir):
    """测试跟踪文件修改"""
    file_path = temp_dir / "test.txt"
    file_path.write_text("content", encoding="utf-8")

    # 第一次跟踪
    file_history.track_file_edit(file_path, "test.txt", 0)

    assert "test.txt" in file_history.state.tracked_files
    assert len(file_history.state.snapshots) == 1
    assert "test.txt" in file_history.state.snapshots[0].tracked_files

    # 第二次跟踪同一文件（应该不重复备份）
    file_history.track_file_edit(file_path, "test.txt", 0)
    assert len(file_history.state.snapshots[0].tracked_files) == 1


def test_make_snapshot(file_history, temp_dir):
    """测试创建快照"""
    file_path = temp_dir / "test.txt"
    file_path.write_text("content", encoding="utf-8")

    file_history.track_file_edit(file_path, "test.txt", 0)
    file_history.make_snapshot(1)

    assert len(file_history.state.snapshots) == 2
    assert file_history.state.snapshots[1].message_index == 1


def test_rewind_to_snapshot(file_history, temp_dir):
    """测试恢复到快照"""
    file_path = temp_dir / "test.txt"

    # 初始内容
    file_path.write_text("version 1", encoding="utf-8")
    file_history.track_file_edit(file_path, "test.txt", 0)
    file_history.make_snapshot(1)

    # 修改文件
    file_path.write_text("version 2", encoding="utf-8")
    file_history.track_file_edit(file_path, "test.txt", 1)
    file_history.make_snapshot(2)

    # 恢复到第一个快照
    restored = file_history.rewind_to_snapshot(temp_dir, 0)

    assert "test.txt" in restored
    assert file_path.read_text(encoding="utf-8") == "version 1"


def test_rewind_deleted_file(file_history, temp_dir):
    """测试恢复已删除的文件"""
    file_path = temp_dir / "test.txt"

    # 文件不存在时创建快照
    file_history.track_file_edit(file_path, "test.txt", 0)
    file_history.make_snapshot(1)

    # 创建文件
    file_path.write_text("new content", encoding="utf-8")
    file_history.track_file_edit(file_path, "test.txt", 1)
    file_history.make_snapshot(2)

    # 恢复到文件不存在的状态
    restored = file_history.rewind_to_snapshot(temp_dir, 0)

    assert "test.txt" in restored
    assert not file_path.exists()


def test_max_snapshots_limit(file_history, temp_dir):
    """测试快照数量限制"""
    file_history.state.max_snapshots = 5

    for i in range(10):
        file_history.make_snapshot(i)

    assert len(file_history.state.snapshots) == 5
    assert file_history.state.snapshots[0].message_index == 5


def test_get_snapshot_info(file_history, temp_dir):
    """测试获取快照信息"""
    file_path = temp_dir / "test.txt"
    file_path.write_text("content", encoding="utf-8")

    file_history.track_file_edit(file_path, "test.txt", 0)
    file_history.make_snapshot(1)

    info = file_history.get_snapshot_info(0)

    assert info["exists"] is True
    assert info["message_index"] == 0
    assert info["tracked_files_count"] == 1
    assert "test.txt" in info["tracked_files"]

