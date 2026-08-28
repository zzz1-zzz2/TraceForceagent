"""run_command 工具：执行 shell 命令。"""

from __future__ import annotations

from coding_agent.model.types import ToolResult
from coding_agent.runtime.base import Runtime
from coding_agent.tools.base import Tool


class RunCommandTool(Tool):
    """执行 shell 命令（独立 subprocess，无 persistent shell）。"""

    name = "run_command"
    description = (
        "Execute a shell command. Each command runs in an independent subprocess "
        "(no persistent shell state). Use 'cwd' to change directory within command "
        "(e.g. 'cd src && python test.py')."
    )
    schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (relative to workspace). Default '.'.",
                "default": ".",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 60, max 600)",
                "default": 60,
            },
        },
        "required": ["command"],
    }

    def execute(self, args: dict, runtime: Runtime) -> ToolResult:
        command = args.get("command", "")
        if not command:
            return ToolResult.fail("Missing required parameter: command")

        cwd = args.get("cwd", ".")
        timeout = min(args.get("timeout", 60), 600)

        # resolve cwd
        try:
            workspace = runtime.workspace.resolve()
            target_cwd = (workspace / cwd).resolve()
            target_cwd.relative_to(workspace)
        except (ValueError, Exception):
            return ToolResult.fail("cwd escapes workspace boundary", is_runtime_error=True)

        try:
            result = runtime.execute(command=command, cwd=target_cwd, timeout=timeout)
        except Exception as e:
            return self.exception_observation(e)

        # 构造 Observation
        output = result.combined_output
        truncated = result.truncated

        # 检测是否是测试失败
        is_validation = self._looks_like_test_command(command) and result.exit_code != 0

        if result.exit_code == 0:
            return ToolResult.ok(
                f"$ {command}\n\n{output}",
                truncated=truncated,
                summary=f"Command OK ({result.duration:.1f}s)",
            )

        # exit != 0
        # 区分 command failure（程序自身失败）和 tool error（runtime error）
        if result.exit_code == -1:  # timeout
            return ToolResult.fail(
                f"$ {command}\n\nTimeout after {timeout}s",
                is_runtime_error=True,
                is_timeout=True,
                truncated=truncated,
                is_validation_failure=False,
            )

        # 命令未找到检测：匹配 POSIX / bash / zsh / cmd / powershell 的"未找到"消息
        # 必须放在 exit_code 127 之前，因为 127 还可能匹配 shell 自身错误（如 /bin/sh 找不到）
        not_found_patterns = [
            "command not found",                    # bash / zsh
            ": not found",                          # POSIX sh (e.g. "/bin/sh: 1: python: not found")
            "is not recognized as",                  # Windows cmd
            "不是内部或外部命令",                     # Windows cmd (Chinese)
            "无法识别",                              # Windows PowerShell
            "no such file or directory",             # 直接执行二进制找不到
        ]
        lower_output = output.lower()
        is_not_found = (
            result.exit_code == 127
            or any(pat in lower_output for pat in not_found_patterns)
        )
        if is_not_found:
            return ToolResult.fail(
                f"$ {command}\n\n{output}\n(executable not found)",
                is_runtime_error=True,
                is_validation_failure=False,
            )

        # 普通程序失败（exit != 0 但命令成功执行）—— 视为 validation failure
        return ToolResult.fail(
            f"$ {command}\n\nexit_code={result.exit_code}\n\n{output}",
            truncated=truncated,
            is_validation_failure=is_validation,
            summary=f"Command failed (exit={result.exit_code})",
        )

    def _looks_like_test_command(self, command: str) -> bool:
        """判断是否是测试命令。"""
        return self.is_test_command(command)

    @staticmethod
    def is_test_command(command: str) -> bool:
        """判断命令是否属于可执行 validation。"""
        import re

        normalized = command.strip().lower()
        patterns = (
            r"(?:^|&&|;|\|\|)\s*(?:[^\s;&|]*/)?(?:python3?|py)\s+-m\s+(?:pytest|unittest|py_compile|compileall)\b",
            r"(?:^|&&|;|\|\|)\s*(?:pytest|py\.test|nosetests|jest|flake8|mypy)\b",
            r"(?:^|&&|;|\|\|)\s*(?:npm|yarn|pnpm)\s+(?:test|build)\b",
            r"(?:^|&&|;|\|\|)\s*(?:npm|yarn|pnpm)\s+run\s+(?:test|build|lint|check)\b",
            r"(?:^|&&|;|\|\|)\s*(?:cargo|go|mvn|gradle|make|tox|nox)\s+(?:test|check|build|vet|lint)\b",
            r"(?:^|&&|;|\|\|)\s*(?:gcc|g\+\+|clang|clang\+\+)\s+[^;&|]*-fsyntax-only\b",
            r"(?:^|&&|;|\|\|)\s*javac\b",
            r"(?:^|&&|;|\|\|)\s*node\s+--check\b",
            r"(?:^|&&|;|\|\|)\s*tsc\b[^;&|]*--noemit\b",
            r"(?:^|&&|;|\|\|)\s*dotnet\s+(?:test|build)\b",
            r"(?:^|&&|;|\|\|)\s*php\s+-l\b",
            r"(?:^|&&|;|\|\|)\s*ruff\s+(?:check|format\s+--check)\b",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)
