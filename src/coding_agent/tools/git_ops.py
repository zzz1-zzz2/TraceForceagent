"""git_diff 工具：查看当前工作区修改。"""

from __future__ import annotations

import subprocess

from coding_agent.model.types import ToolResult
from coding_agent.runtime.base import Runtime
from coding_agent.tools.base import Tool


class GitDiffTool(Tool):
    """查看 git diff（用于 finish 前自检）。"""

    name = "git_diff"
    description = "Show current git diff in the workspace. Use before finish() to verify changes."
    schema = {
        "type": "object",
        "properties": {
            "max_lines": {
                "type": "integer",
                "description": "Maximum diff lines to return (default 200)",
                "default": 200,
            },
        },
        "required": [],
    }

    def execute(self, args: dict, runtime: Runtime) -> ToolResult:
        max_lines = min(args.get("max_lines", 200), 2000)

        try:
            proc = subprocess.run(
                ["git", "diff", "--no-color"],
                cwd=str(runtime.workspace),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.fail("git diff timeout", is_runtime_error=True)
        except FileNotFoundError:
            return ToolResult.fail(
                "git not installed or workspace not a git repo",
                is_runtime_error=True,
            )
        except Exception as e:
            return self.exception_observation(e)

        if proc.returncode != 0:
            return ToolResult.fail(f"git diff error: {proc.stderr}", is_runtime_error=True)

        output = proc.stdout
        if not output.strip():
            return ToolResult.ok("(no changes yet)")

        lines = output.splitlines()
        truncated = len(lines) > max_lines
        if truncated:
            body = "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
        else:
            body = output

        return ToolResult.ok(body, truncated=truncated)