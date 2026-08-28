"""apply_patch create 模式不覆盖已有文件 — 单元测试。

P1-1 关键回归。

放在独立文件而不是 test_tools_boundary.py，因为后者有 pre-existing
collection error（import 循环），与本次修复无关。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.config import AgentConfig
from coding_agent.runtime.local import LocalRuntime


@pytest.fixture
def runtime(tmp_path):
    cfg = AgentConfig(workspace_root=tmp_path)
    return LocalRuntime(workspace=tmp_path, config=cfg)


class TestCreateNoOverwrite:
    def test_create_new_file_succeeds(self, runtime, tmp_path):
        """文件不存在 → create 成功。"""
        from coding_agent.tools.patch import ApplyPatchTool

        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "new.txt", "mode": "create", "new_string": "content"},
            runtime,
        )
        assert result.success
        assert (tmp_path / "new.txt").read_text() == "content"

    def test_create_refuses_overwrite_existing_file(self, runtime, tmp_path):
        """P1-1：create 模式拒绝覆盖已存在文件，避免误删内容。"""
        from coding_agent.tools.patch import ApplyPatchTool

        existing = tmp_path / "existing.txt"
        existing.write_text("IMPORTANT content that must not be lost")

        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "existing.txt", "mode": "create", "content": "OVERWRITTEN!"},
            runtime,
        )
        assert not result.success
        assert "already exists" in result.error.lower()
        # 原文件未受影响
        assert existing.read_text() == "IMPORTANT content that must not be lost"

    def test_create_refuses_overwrite_empty_existing_file(self, runtime, tmp_path):
        """即使是空文件也不能覆盖（避免静默清空）。"""
        from coding_agent.tools.patch import ApplyPatchTool

        empty = tmp_path / "empty.txt"
        empty.write_text("")

        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "empty.txt", "mode": "create", "content": "now non-empty"},
            runtime,
        )
        assert not result.success
        assert empty.read_text() == ""

    def test_create_failure_no_partial_write(self, runtime, tmp_path):
        """create 失败时，原文件不能被部分写入覆盖；.tmp 文件应被清理。"""
        from coding_agent.tools.patch import ApplyPatchTool

        existing = tmp_path / "atomic.txt"
        original = "line1\nline2\nline3\n"
        existing.write_text(original)

        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "atomic.txt", "mode": "create", "content": "garbage"},
            runtime,
        )
        assert not result.success
        assert existing.read_text() == original
        # 临时文件不应残留
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert all(f.name != "atomic.tmp" for f in tmp_files)

    def test_modify_still_works_on_existing(self, runtime, tmp_path):
        """modify 模式照常工作（不被 P1-1 影响）。"""
        from coding_agent.tools.patch import ApplyPatchTool

        existing = tmp_path / "edit.txt"
        existing.write_text("hello world")

        tool = ApplyPatchTool()
        result = tool.execute(
            {
                "path": "edit.txt",
                "mode": "modify",
                "old_string": "hello",
                "new_string": "goodbye",
            },
            runtime,
        )
        assert result.success
        assert existing.read_text() == "goodbye world"

    def test_delete_still_works_on_existing(self, runtime, tmp_path):
        """delete 模式照常工作。"""
        from coding_agent.tools.patch import ApplyPatchTool

        existing = tmp_path / "doomed.txt"
        existing.write_text("goodbye")

        tool = ApplyPatchTool()
        result = tool.execute({"path": "doomed.txt", "mode": "delete"}, runtime)
        assert result.success
        assert not existing.exists()


class TestCreateErrorMessage:
    """错误信息必须明确告诉模型该怎么修复。"""

    def test_error_message_suggests_modify_mode(self, runtime, tmp_path):
        from coding_agent.tools.patch import ApplyPatchTool

        existing = tmp_path / "x.txt"
        existing.write_text("old")

        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "x.txt", "mode": "create", "content": "new"},
            runtime,
        )
        assert not result.success
        # 必须告诉模型用 modify
        assert "modify" in result.error.lower()
        # 必须告诉模型换 path
        assert "new path" in result.error.lower() or "pick" in result.error.lower()
