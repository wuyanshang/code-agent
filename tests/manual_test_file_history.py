"""手动测试文件历史功能"""
from pathlib import Path
import tempfile
import sys

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_agent.services.file_history import FileHistoryManager


def test_basic_workflow():
    """测试基本工作流程"""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        backup_root = temp_dir / "backups"

        # 创建文件历史管理器
        fh = FileHistoryManager(backup_root, "test-session")
        print("✓ 创建FileHistoryManager")

        # 创建测试文件
        test_file = temp_dir / "test.txt"
        test_file.write_text("version 1", encoding="utf-8")
        print("✓ 创建测试文件: version 1")

        # 跟踪文件修改
        fh.track_file_edit(test_file, "test.txt", 0)
        print(f"✓ 跟踪文件修改，快照数: {len(fh.state.snapshots)}")

        # 创建快照
        fh.make_snapshot(1)
        print(f"✓ 创建快照，快照数: {len(fh.state.snapshots)}")

        # 修改文件
        test_file.write_text("version 2", encoding="utf-8")
        print("✓ 修改文件: version 2")

        # 再次跟踪
        fh.track_file_edit(test_file, "test.txt", 1)
        fh.make_snapshot(2)
        print(f"✓ 创建第二个快照，快照数: {len(fh.state.snapshots)}")

        # 验证当前内容
        current = test_file.read_text(encoding="utf-8")
        print(f"✓ 当前文件内容: {current}")
        assert current == "version 2", f"Expected 'version 2', got '{current}'"

        # 恢复到第一个快照
        restored = fh.rewind_to_snapshot(temp_dir, 0)
        print(f"✓ 恢复到快照0，恢复文件数: {len(restored)}")

        # 验证恢复后的内容
        restored_content = test_file.read_text(encoding="utf-8")
        print(f"✓ 恢复后文件内容: {restored_content}")
        assert restored_content == "version 1", f"Expected 'version 1', got '{restored_content}'"

        print("\n✅ 所有测试通过！")


if __name__ == "__main__":
    test_basic_workflow()
