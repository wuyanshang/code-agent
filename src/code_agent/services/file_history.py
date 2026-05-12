from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class FileBackup:
    """单个文件的备份记录"""
    backup_path: Path | None  # None表示文件不存在（新建文件的情况）
    version: int
    backup_time: datetime
    original_path: str


@dataclass
class FileHistorySnapshot:
    """文件历史快照"""
    message_index: int  # 关联的消息索引
    tracked_files: dict[str, FileBackup] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class FileHistoryState:
    """文件历史状态"""
    snapshots: list[FileHistorySnapshot] = field(default_factory=list)
    tracked_files: set[str] = field(default_factory=set)
    max_snapshots: int = 100


class FileHistoryManager:
    """文件历史管理器"""

    def __init__(self, backup_root: Path, session_id: str):
        self.backup_root = backup_root / session_id
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.state = FileHistoryState()

    def _get_file_hash(self, content: str) -> str:
        """计算文件内容的hash"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _get_backup_filename(self, file_path: str, content: str) -> str:
        """生成备份文件名: {path_hash}_{content_hash}"""
        # 使用文件路径的hash
        path_hash = hashlib.sha256(file_path.encode("utf-8")).hexdigest()[:12]
        # 使用内容的hash
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        return f"{path_hash}_{content_hash}"

    def create_backup(self, file_path: Path, relative_path: str) -> FileBackup:
        """创建文件备份"""
        # 如果文件不存在，记录为None（新建文件的情况）
        if not file_path.exists():
            return FileBackup(
                backup_path=None,
                version=1,
                backup_time=datetime.now(),
                original_path=relative_path,
            )

        # 读取文件内容
        content = file_path.read_text(encoding="utf-8")

        # 生成备份文件名（基于路径和内容hash）
        backup_filename = self._get_backup_filename(relative_path, content)
        backup_path = self.backup_root / backup_filename

        # 如果备份已存在，直接返回（内容相同的去重）
        if backup_path.exists():
            return FileBackup(
                backup_path=backup_path,
                version=1,
                backup_time=datetime.now(),
                original_path=relative_path,
            )

        # 写入备份文件
        backup_path.write_text(content, encoding="utf-8")

        return FileBackup(
            backup_path=backup_path,
            version=1,
            backup_time=datetime.now(),
            original_path=relative_path,
        )

    def track_file_edit(self, file_path: Path, relative_path: str, message_index: int) -> None:
        """跟踪文件修改（在修改前调用）"""
        # 检查最近的快照是否已经跟踪了这个文件
        if self.state.snapshots:
            last_snapshot = self.state.snapshots[-1]
            if relative_path in last_snapshot.tracked_files:
                # 已经在最近快照中跟踪，无需重复备份
                return

        # 创建备份
        backup = self.create_backup(file_path, relative_path)

        # 如果没有快照，创建一个
        if not self.state.snapshots:
            self.state.snapshots.append(
                FileHistorySnapshot(
                    message_index=message_index,
                    tracked_files={},
                )
            )

        # 添加到最近的快照
        last_snapshot = self.state.snapshots[-1]
        last_snapshot.tracked_files[relative_path] = backup
        self.state.tracked_files.add(relative_path)

    def make_snapshot(self, message_index: int) -> None:
        """创建新快照"""
        # 创建新快照
        new_snapshot = FileHistorySnapshot(
            message_index=message_index,
            tracked_files={},
        )
        self.state.snapshots.append(new_snapshot)

        # 限制快照数量
        if len(self.state.snapshots) > self.state.max_snapshots:
            self.state.snapshots = self.state.snapshots[-self.state.max_snapshots :]

    def rewind_to_snapshot(self, project_root: Path, snapshot_index: int = -1) -> list[str]:
        """恢复到指定快照

        Args:
            project_root: 项目根目录
            snapshot_index: 快照索引，-1表示上一个快照

        Returns:
            恢复的文件路径列表
        """
        if not self.state.snapshots:
            raise ValueError("没有可用的快照")

        # 获取目标快照
        if snapshot_index < 0:
            snapshot_index = len(self.state.snapshots) + snapshot_index

        if snapshot_index < 0 or snapshot_index >= len(self.state.snapshots):
            raise ValueError(f"快照索引 {snapshot_index} 超出范围")

        target_snapshot = self.state.snapshots[snapshot_index]
        restored_files: list[str] = []

        # 恢复所有跟踪的文件
        for relative_path in self.state.tracked_files:
            file_path = project_root / relative_path

            # 查找该文件在目标快照中的备份
            backup = target_snapshot.tracked_files.get(relative_path)

            if backup is None:
                # 在目标快照中没有这个文件的记录，查找第一个版本
                backup = self._find_first_backup(relative_path, snapshot_index)

            if backup is None:
                # 找不到备份，跳过
                continue

            # 恢复文件
            if backup.backup_path is None:
                # 文件在快照时不存在，删除当前文件
                if file_path.exists():
                    file_path.unlink()
                    restored_files.append(relative_path)
            else:
                # 从备份恢复
                if backup.backup_path.exists():
                    content = backup.backup_path.read_text(encoding="utf-8")
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(content, encoding="utf-8")
                    restored_files.append(relative_path)

        return restored_files

    def _find_first_backup(self, relative_path: str, before_index: int) -> FileBackup | None:
        """查找文件的第一个备份版本（在指定快照之前）"""
        for i in range(before_index, -1, -1):
            snapshot = self.state.snapshots[i]
            if relative_path in snapshot.tracked_files:
                return snapshot.tracked_files[relative_path]
        return None

    def get_snapshot_info(self, snapshot_index: int = -1) -> dict[str, Any]:
        """获取快照信息"""
        if not self.state.snapshots:
            return {"exists": False}

        if snapshot_index < 0:
            snapshot_index = len(self.state.snapshots) + snapshot_index

        if snapshot_index < 0 or snapshot_index >= len(self.state.snapshots):
            return {"exists": False}

        snapshot = self.state.snapshots[snapshot_index]
        return {
            "exists": True,
            "message_index": snapshot.message_index,
            "timestamp": snapshot.timestamp.isoformat(),
            "tracked_files_count": len(snapshot.tracked_files),
            "tracked_files": list(snapshot.tracked_files.keys()),
        }

    def cleanup(self) -> None:
        """清理备份文件"""
        if self.backup_root.exists():
            shutil.rmtree(self.backup_root)

