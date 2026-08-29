"""P2-1E.3 WorkspaceChangeTracker 回归测试。

覆盖：
- 非 Git workspace：创建 / 修改 / 删除；
- 恢复原状（修改 → 再改回原内容）：content_hash 一致 → 净变化为空；
- 不跟随 symlink；symlink 本身记录为 kind=symlink；
- 噪声目录被排除（.git / .venv / __pycache__）；
- 模式位变化（chmod）计入 modified；
- Shell 修改的文件（非 apply_patch）也被识别为 mutation；
- WorkspaceChangeTracker.diff_since 与快照的衔接；
- AgentState.record_workspace_change 集成。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from coding_agent.agent.state import AgentState
from coding_agent.workspace.tracker import (
    WorkspaceChangeTracker,
    diff_snapshots,
    snapshot_workspace,
)

# ============================================================
# snapshot_workspace 基本行为
# ============================================================


class TestSnapshotBasics:
    def test_empty_workspace_returns_empty_snapshot(self, tmp_path: Path) -> None:
        snap = snapshot_workspace(tmp_path, prefer_git=False)
        assert snap.entries == ()
        assert not snap.is_git

    def test_files_appear_in_snapshot(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("world", encoding="utf-8")
        snap = snapshot_workspace(tmp_path, prefer_git=False)
        paths = {e.path for e in snap.entries}
        assert "a.txt" in paths
        assert "sub/b.txt" in paths

    def test_noisy_dirs_excluded(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("x = 1")
        (tmp_path / "kept.txt").write_text("yes")
        snap = snapshot_workspace(tmp_path, prefer_git=False)
        paths = {e.path for e in snap.entries}
        assert ".git/HEAD" not in paths
        assert "__pycache__/x.pyc" not in paths
        assert ".venv/lib.py" not in paths
        assert "kept.txt" in paths

    def test_symlink_not_followed(self, tmp_path: Path) -> None:
        target = tmp_path / "real.txt"
        target.write_text("real", encoding="utf-8")
        link = tmp_path / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            import pytest
            pytest.skip("symlink not supported on this filesystem")
        snap = snapshot_workspace(tmp_path, prefer_git=False)
        by_path = {e.path: e for e in snap.entries}
        assert "real.txt" in by_path
        assert by_path["link.txt"].kind == "symlink"
        assert by_path["link.txt"].content_hash is None


# ============================================================
# diff_snapshots 行为
# ============================================================


class TestDiff:
    def test_created_file(self, tmp_path: Path) -> None:
        before = snapshot_workspace(tmp_path, prefer_git=False)
        (tmp_path / "new.txt").write_text("hi", encoding="utf-8")
        after = snapshot_workspace(tmp_path, prefer_git=False)
        change = diff_snapshots(before, after)
        assert change.created == ("new.txt",)
        assert change.modified == ()
        assert change.deleted == ()
        assert change.has_changes

    def test_modified_file(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("v1", encoding="utf-8")
        before = snapshot_workspace(tmp_path, prefer_git=False)
        f.write_text("v2", encoding="utf-8")
        after = snapshot_workspace(tmp_path, prefer_git=False)
        change = diff_snapshots(before, after)
        assert change.created == ()
        assert change.modified == ("f.txt",)
        assert change.deleted == ()

    def test_deleted_file(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("x", encoding="utf-8")
        before = snapshot_workspace(tmp_path, prefer_git=False)
        f.unlink()
        after = snapshot_workspace(tmp_path, prefer_git=False)
        change = diff_snapshots(before, after)
        assert change.deleted == ("f.txt",)

    def test_no_change_when_identical(self, tmp_path: Path) -> None:
        (tmp_path / "x.txt").write_text("same", encoding="utf-8")
        before = snapshot_workspace(tmp_path, prefer_git=False)
        after = snapshot_workspace(tmp_path, prefer_git=False)
        change = diff_snapshots(before, after)
        assert not change.has_changes

    def test_restore_to_original_no_net_change(self, tmp_path: Path) -> None:
        """修改后又改回原内容（content_hash 一致）→ 净变化为空。"""
        f = tmp_path / "f.txt"
        f.write_text("original", encoding="utf-8")
        before = snapshot_workspace(tmp_path, prefer_git=False)
        f.write_text("intermediate garbage", encoding="utf-8")
        f.write_text("original", encoding="utf-8")
        after = snapshot_workspace(tmp_path, prefer_git=False)
        change = diff_snapshots(before, after)
        assert not change.has_changes, (
            f"expected no net change, got {change.created}/{change.modified}/{change.deleted}"
        )

    def test_permission_change_counts_as_modified(self, tmp_path: Path) -> None:
        """chmod 变化（mode 位）应被识别。"""
        f = tmp_path / "x.txt"
        f.write_text("same", encoding="utf-8")
        os.chmod(f, 0o644)
        before = snapshot_workspace(tmp_path, prefer_git=False)
        os.chmod(f, 0o600)
        after = snapshot_workspace(tmp_path, prefer_git=False)
        change = diff_snapshots(before, after)
        assert "x.txt" in change.modified

    def test_shell_created_file_is_detected(self, tmp_path: Path) -> None:
        """非 apply_patch 路径（shell 命令）写入文件 → 仍然识别 mutation。"""
        # 先建一个稳定起点。
        (tmp_path / "anchor.txt").write_text("anchor", encoding="utf-8")
        before = snapshot_workspace(tmp_path, prefer_git=False)
        # 模拟 shell：直接写入新文件。
        (tmp_path / "shell_wrote.txt").write_text("by shell", encoding="utf-8")
        after = snapshot_workspace(tmp_path, prefer_git=False)
        change = diff_snapshots(before, after)
        assert "shell_wrote.txt" in change.created


# ============================================================
# WorkspaceChangeTracker 集成
# ============================================================


class TestTracker:
    def test_tracker_snapshot_and_diff_since(self, tmp_path: Path) -> None:
        tracker = WorkspaceChangeTracker(tmp_path, prefer_git=False)
        prev = tracker.snapshot()
        (tmp_path / "via_tracker.txt").write_text("ok", encoding="utf-8")
        change = tracker.diff_since(prev)
        assert change.created == ("via_tracker.txt",)

    def test_tracker_diff_since_twice(self, tmp_path: Path) -> None:
        """连续两次 diff_since 必须独立工作（不污染 prev）。"""
        tracker = WorkspaceChangeTracker(tmp_path, prefer_git=False)
        prev1 = tracker.snapshot()
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        change1 = tracker.diff_since(prev1)
        assert change1.created == ("a.txt",)
        prev2 = tracker.snapshot()
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        change2 = tracker.diff_since(prev2)
        assert change2.created == ("b.txt",)
        assert "a.txt" not in change2.created


# ============================================================
# Git 工作区（需要 git 可用）
# ============================================================


class TestGitWorkspace:
    @staticmethod
    def _git_available() -> bool:
        try:
            return subprocess.run(
                ["git", "--version"], capture_output=True, check=False
            ).returncode == 0
        except FileNotFoundError:
            return False

    def test_git_repo_detection_and_untracked(self, tmp_path: Path) -> None:
        if not self._git_available():
            import pytest
            pytest.skip("git not available")
        # 初始化一个 git repo；先提交一个文件。
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=tmp_path, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "tester"], cwd=tmp_path, check=True,
        )
        (tmp_path / "tracked.txt").write_text("init", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True,
        )

        before = snapshot_workspace(tmp_path, prefer_git=True)
        assert before.is_git
        paths_before = {e.path for e in before.entries}
        assert "tracked.txt" in paths_before

        # 加一个 untracked 文件 + 改 tracked 文件。
        (tmp_path / "tracked.txt").write_text("changed", encoding="utf-8")
        (tmp_path / "untracked.txt").write_text("new", encoding="utf-8")
        after = snapshot_workspace(tmp_path, prefer_git=True)
        change = diff_snapshots(before, after)
        # tracked.txt 内容变化 + untracked.txt 新建 → 至少这两个。
        assert "tracked.txt" in change.modified
        assert "untracked.txt" in change.created


# ============================================================
# AgentState.record_workspace_change 集成
# ============================================================


class TestAgentStateIntegration:
    def test_record_workspace_change_updates_mutated_state(self, tmp_path: Path) -> None:
        from coding_agent.workspace.tracker import WorkspaceChange

        state = AgentState.initialize(task="t", workspace=tmp_path)
        state.ready_to_finish = True  # 假设上一轮 validation 已通过
        change = WorkspaceChange(
            created=("foo.txt",),
            modified=("bar.txt",),
            deleted=("baz.txt",),
        )
        state.record_workspace_change(change, step=5)
        assert state.modified_files == {"foo.txt", "bar.txt", "baz.txt"}
        assert state.last_mutation_step == 5
        # mutation 出现 → ready_to_finish 必须重置。
        assert state.ready_to_finish is False

    def test_record_workspace_change_no_changes_is_noop(self, tmp_path: Path) -> None:
        from coding_agent.workspace.tracker import WorkspaceChange

        state = AgentState.initialize(task="t", workspace=tmp_path)
        state.ready_to_finish = True
        state.last_mutation_step = 3
        change = WorkspaceChange()
        state.record_workspace_change(change, step=10)
        # 没有净变化 → mutation step 与 ready_to_finish 都不动。
        assert state.last_mutation_step == 3
        assert state.ready_to_finish is True
        assert state.modified_files == set()
