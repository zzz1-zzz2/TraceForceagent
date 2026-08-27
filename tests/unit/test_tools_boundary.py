"""Workspace boundary 单元测试。"""

from pathlib import Path

import pytest

from coding_agent.config import AgentConfig
from coding_agent.runtime.local import LocalRuntime
from coding_agent.tools.filesystem import ListFilesTool, ReadFileTool


@pytest.fixture
def runtime(tmp_path):
    cfg = AgentConfig(workspace_root=tmp_path)
    return LocalRuntime(workspace=tmp_path, config=cfg)


class TestListFilesBoundary:
    def test_relative_dot_works(self, runtime):
        tool = ListFilesTool()
        result = tool.execute({"path": "."}, runtime)
        assert result.success

    def test_parent_traversal_denied(self, runtime):
        tool = ListFilesTool()
        result = tool.execute({"path": "../etc"}, runtime)
        assert not result.success
        assert "escape" in result.error.lower() or "boundary" in result.error.lower()

    def test_double_parent_traversal_denied(self, runtime):
        tool = ListFilesTool()
        result = tool.execute({"path": "../../../"}, runtime)
        assert not result.success


class TestReadFileBoundary:
    def test_read_legitimate_file(self, runtime, tmp_path):
        f = tmp_path / "ok.txt"
        f.write_text("hello world\n")
        tool = ReadFileTool()
        result = tool.execute({"path": "ok.txt"}, runtime)
        assert result.success
        assert "hello world" in result.content

    def test_read_escape_denied(self, runtime):
        tool = ReadFileTool()
        result = tool.execute({"path": "../../etc/passwd"}, runtime)
        assert not result.success
        assert "escape" in result.error.lower() or "boundary" in result.error.lower()

    def test_read_nonexistent_returns_error(self, runtime):
        tool = ReadFileTool()
        result = tool.execute({"path": "nope.txt"}, runtime)
        assert not result.success
        assert "not found" in result.error.lower()

    def test_read_line_window(self, runtime, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("\n".join(f"line {i}" for i in range(1, 11)))
        tool = ReadFileTool()
        result = tool.execute({"path": "lines.txt", "start_line": 3, "end_line": 5}, runtime)
        assert result.success
        assert "line 3" in result.content
        assert "line 5" in result.content
        assert "line 2" not in result.content
        assert "line 6" not in result.content
        assert result.truncated  # 还有更多行


class TestApplyPatchBoundary:
    def test_modify_inside_workspace(self, runtime, tmp_path):
        from coding_agent.tools.patch import ApplyPatchTool

        f = tmp_path / "x.txt"
        f.write_text("old")
        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "x.txt", "mode": "modify", "old_string": "old", "new_string": "new"},
            runtime,
        )
        assert result.success
        assert f.read_text() == "new"

    def test_modify_escape_denied(self, runtime):
        from coding_agent.tools.patch import ApplyPatchTool

        tool = ApplyPatchTool()
        result = tool.execute(
            {
                "path": "../../etc/hosts",
                "mode": "modify",
                "old_string": "x",
                "new_string": "y",
            },
            runtime,
        )
        assert not result.success

    def test_modify_old_string_not_found(self, runtime, tmp_path):
        from coding_agent.tools.patch import ApplyPatchTool

        f = tmp_path / "y.txt"
        f.write_text("hello")
        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "y.txt", "mode": "modify", "old_string": "nothere", "new_string": "x"},
            runtime,
        )
        assert not result.success
        assert "not found" in result.error.lower()

    def test_modify_ambiguous_old_string(self, runtime, tmp_path):
        from coding_agent.tools.patch import ApplyPatchTool

        f = tmp_path / "z.txt"
        f.write_text("a a a")
        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "z.txt", "mode": "modify", "old_string": "a", "new_string": "b"},
            runtime,
        )
        assert not result.success
        assert "matches" in result.error.lower() or "unique" in result.error.lower()

    def test_create_new_file(self, runtime, tmp_path):
        from coding_agent.tools.patch import ApplyPatchTool

        tool = ApplyPatchTool()
        result = tool.execute(
            {"path": "new.txt", "mode": "create", "new_string": "content"},
            runtime,
        )
        assert result.success
        assert (tmp_path / "new.txt").read_text() == "content"