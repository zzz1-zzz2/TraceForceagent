"""Shell tool 单元测试：timeout / 正常退出 / 测试失败。"""

from pathlib import Path

import pytest

from coding_agent.config import AgentConfig
from coding_agent.model.types import ToolResult
from coding_agent.runtime.local import LocalRuntime
from coding_agent.tools.shell import RunCommandTool


@pytest.fixture
def runtime(tmp_path):
    cfg = AgentConfig(workspace_root=tmp_path)
    return LocalRuntime(workspace=tmp_path, config=cfg)


@pytest.fixture
def tool():
    return RunCommandTool()


class TestRunCommandSuccess:
    def test_simple_command(self, runtime, tool):
        result = tool.execute({"command": "echo hello", "timeout": 10}, runtime)
        assert isinstance(result, ToolResult)
        assert result.success
        assert "hello" in result.content

    def test_cwd_change_in_command(self, runtime, tool, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        result = tool.execute(
            {"command": "cd sub && pwd", "timeout": 10},
            runtime,
        )
        assert result.success


class TestRunCommandFailure:
    def test_nonzero_exit_is_not_validation_failure(self, runtime, tool):
        result = tool.execute(
            {"command": "python -c 'import sys; sys.exit(1)'", "timeout": 10},
            runtime,
        )
        assert not result.success
        # 不是 pytest，所以不是 validation failure
        assert not result.is_validation_failure

    def test_pytest_failure_marked_as_validation_failure(self, runtime, tool):
        """pytest 失败应标记 is_validation_failure=True。"""
        result = tool.execute(
            {"command": "python -m pytest nonexistent_test", "timeout": 30},
            runtime,
        )
        assert not result.success
        assert result.is_validation_failure


class TestRunCommandTimeout:
    def test_timeout_marks_is_timeout(self, runtime, tool):
        """超时命令应标记 is_timeout=True。"""
        result = tool.execute(
            {"command": "sleep 5", "timeout": 1},
            runtime,
        )
        assert not result.success
        assert result.is_timeout
        assert result.is_runtime_error


class TestRunCommandBoundary:
    def test_cwd_escape_denied(self, runtime, tool):
        result = tool.execute(
            {"command": "ls", "cwd": "../../etc", "timeout": 5},
            runtime,
        )
        assert not result.success
        assert result.is_runtime_error


class TestRunCommandNotFound:
    def test_executable_not_found(self, runtime, tool):
        result = tool.execute(
            {"command": "definitely_not_a_real_command_xyz123", "timeout": 5},
            runtime,
        )
        assert not result.success
        assert result.is_runtime_error