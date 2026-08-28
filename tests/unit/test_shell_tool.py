"""Shell tool 单元测试：timeout / 正常退出 / 测试失败。"""

import sys

import pytest

from coding_agent.config import AgentConfig
from coding_agent.model.types import ToolResult
from coding_agent.runtime.local import LocalRuntime
from coding_agent.tools.shell import RunCommandTool

# 用 sys.executable 而不是裸 "python" —— 后者在 venv / Docker 等环境里未必在 PATH。
PY = sys.executable


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
            {"command": f"{PY} -c 'import sys; sys.exit(1)'", "timeout": 10},
            runtime,
        )
        assert not result.success
        # 不是 pytest，所以不是 validation failure
        assert not result.is_validation_failure

    def test_pytest_failure_marked_as_validation_failure(self, runtime, tool):
        """pytest 失败应标记 is_validation_failure=True。"""
        # 故意选个不存在的测试，确保 pytest 正常 exit 但状态失败
        result = tool.execute(
            {"command": f"{PY} -m pytest nonexistent_test_xyz", "timeout": 30},
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


class TestValidationCommandClassifier:
    @pytest.mark.parametrize(
        "command",
        [
            "ls tests/",
            "echo pytest",
            'printf "test complete"',
            "git diff -- tests/test_app.py",
        ],
    )
    def test_non_validation_commands_are_not_classified(self, command):
        assert not RunCommandTool.is_test_command(command)

    @pytest.mark.parametrize(
        "command",
        [
            "pytest -q",
            f"{PY} -m pytest tests",
            "python3 -m py_compile app.py",
            "gcc -fsyntax-only main.c",
            "g++ -fsyntax-only main.cpp",
            "javac Main.java",
            "node --check app.js",
            "tsc --noEmit",
            "dotnet test",
            "dotnet build",
            "php -l index.php",
        ],
    )
    def test_executable_validation_commands_are_classified(self, command):
        assert RunCommandTool.is_test_command(command)
