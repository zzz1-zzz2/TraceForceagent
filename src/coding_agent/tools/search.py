"""search_code 工具：基于 ripgrep 的代码搜索。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from coding_agent.model.types import ToolResult
from coding_agent.runtime.base import Runtime
from coding_agent.tools.base import Tool


class SearchCodeTool(Tool):
    """使用 ripgrep 搜索代码。"""

    name = "search_code"
    description = (
        "Search for text patterns in files using ripgrep. "
        "Returns matching lines with file:line:content format."
    )
    schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Pattern to search for (regex supported)",
            },
            "path": {
                "type": "string",
                "description": "Path to search within (relative to workspace). Default '.'.",
                "default": ".",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '*.py')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum matches to return (default 50)",
                "default": 50,
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context around each match (default 2)",
                "default": 2,
            },
        },
        "required": ["query"],
    }

    def execute(self, args: dict, runtime: Runtime) -> ToolResult:
        if not shutil.which("rg"):
            return ToolResult.fail(
                "ripgrep (rg) not installed. Run: sudo apt install ripgrep",
                is_runtime_error=True,
            )

        query = args.get("query", "")
        path_str = args.get("path", ".")
        file_pattern = args.get("file_pattern", "")
        max_results = min(args.get("max_results", 50), 500)
        context_lines = args.get("context_lines", 2)

        if not query:
            return ToolResult.fail("Missing required parameter: query")

        # resolve path
        try:
            workspace = runtime.workspace.resolve()
            target = (workspace / path_str).resolve()
            target.relative_to(workspace)  # boundary check
        except (ValueError, Exception):
            return ToolResult.fail("Path escapes workspace boundary", is_runtime_error=True)

        if not target.exists():
            return ToolResult.fail(f"Path not found: {path_str}", is_runtime_error=True)

        cmd = [
            "rg",
            "--no-heading",
            "--line-numbers",
            f"--context", str(context_lines),
            "--max-columns", "200",
            "--max-columns-preview",  # truncate long lines
        ]
        if file_pattern:
            cmd.extend(["--glob", file_pattern])
        cmd.extend(["--", query, str(target)])

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.fail("Search timeout", is_runtime_error=True)
        except Exception as e:
            return self.exception_observation(e)

        # ripgrep exit code: 0=found, 1=no match, 2=error
        if proc.returncode == 2:
            return ToolResult.fail(f"Search error: {proc.stderr.strip()}", is_runtime_error=True)

        if proc.returncode == 1:
            return ToolResult.ok(
                f"No matches found for '{query}' in {path_str}.\n"
                f"Try simpler query or different path."
            )

        lines = proc.stdout.splitlines()
        truncated = False
        if len(lines) > max_results:
            lines = lines[:max_results]
            truncated = True

        body = "\n".join(lines)
        if truncated:
            body += f"\n... (more results truncated, max_results={max_results})"

        # 转为相对路径
        body = body.replace(str(workspace) + "/", "")

        return ToolResult.ok(
            f"Found {len(lines)} matches for '{query}':\n\n{body}",
            truncated=truncated,
        )