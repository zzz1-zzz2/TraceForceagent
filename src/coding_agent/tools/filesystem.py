"""文件系统类工具：list_files、read_file。

设计要点：
- Workspace boundary 强制：所有 path 必须 resolve 后仍在 workspace 内
- read_file 默认 200 行窗口
- list_files 默认 max_depth=3
"""

from __future__ import annotations

import os
from pathlib import Path

from coding_agent.model.types import ToolResult
from coding_agent.runtime.base import Runtime, ToolExecutionContext
from coding_agent.tools.base import Tool


class _FileSystemToolBase(Tool):
    """文件系统类工具基类，共享 path 校验逻辑。"""

    def _resolve_path(self, path_str: str, runtime: Runtime) -> Path | None:
        """解析并校验路径在 workspace 内。"""
        try:
            workspace = runtime.workspace.resolve()
            target = (workspace / path_str).resolve()
            # 必须在 workspace 内
            target.relative_to(workspace)
            return target
        except ValueError:
            return None
        except Exception:
            return None

    def _fail_escape(self) -> ToolResult:
        return ToolResult.fail(
            "Path escapes workspace boundary. Operation denied.",
            is_runtime_error=True,
        )


class ListFilesTool(_FileSystemToolBase):
    """列出目录结构。"""

    name = "list_files"
    description = (
        "List files and directories under a path within the workspace. "
        "Returns a tree-like listing with depth control."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to workspace. Default '.'",
                "default": ".",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum directory depth (default 3)",
                "default": 3,
            },
            "max_entries": {
                "type": "integer",
                "description": "Maximum number of entries to return (default 200)",
                "default": 200,
            },
        },
        "required": [],
    }

    def execute(self, args: dict, runtime: Runtime, context: ToolExecutionContext | None = None) -> ToolResult:
        path_str = args.get("path", ".")
        max_depth = min(args.get("max_depth", 3), 10)
        max_entries = min(args.get("max_entries", 200), 1000)

        target = self._resolve_path(path_str, runtime)
        if target is None:
            return self._fail_escape()

        if not target.exists():
            return ToolResult.fail(f"Path not found: {path_str}", is_runtime_error=True)

        if target.is_file():
            return ToolResult.ok(f"[file] {path_str}")

        # 列出目录
        lines = []
        count = 0
        try:
            for root, dirs, files in os.walk(target):
                # 跳过常见大目录
                dirs[:] = [
                    d for d in dirs
                    if d not in {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".pytest_cache"}
                ]
                rel = Path(root).relative_to(target)
                depth = 0 if rel == Path(".") else len(rel.parts)
                if depth >= max_depth:
                    dirs.clear()
                    continue

                if depth == 0:
                    prefix = ""
                else:
                    prefix = "  " * depth

                if depth > 0:
                    lines.append(f"{prefix[:-2]}{rel.parts[-1]}/")
                    prefix = "  " * (depth + 1)
                else:
                    prefix = ""

                # 排序：目录在前
                for name in sorted(dirs):
                    if count >= max_entries:
                        break
                    lines.append(f"{prefix}{name}/")
                    count += 1
                for name in sorted(files):
                    if count >= max_entries:
                        break
                    lines.append(f"{prefix}{name}")
                    count += 1

                if count >= max_entries:
                    lines.append(f"... (truncated, more than {max_entries} entries)")
                    break
        except Exception as e:
            return self.exception_observation(e)

        return ToolResult.ok("\n".join(lines) if lines else "(empty directory)")


class ReadFileTool(_FileSystemToolBase):
    """读取文件指定行区间。"""

    name = "read_file"
    description = (
        "Read a file's content, optionally within a line range. "
        "Default reads lines 1-200 to keep context manageable."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to workspace",
            },
            "start_line": {
                "type": "integer",
                "description": "Start line (1-indexed). Default 1.",
                "default": 1,
            },
            "end_line": {
                "type": "integer",
                "description": "End line (inclusive). Default 200.",
                "default": 200,
            },
        },
        "required": ["path"],
    }

    DEFAULT_WINDOW = 200

    def execute(self, args: dict, runtime: Runtime, context: ToolExecutionContext | None = None) -> ToolResult:
        path_str = args.get("path", "")
        if not path_str:
            return ToolResult.fail("Missing required parameter: path")

        start = max(1, args.get("start_line", 1))
        end = max(start, args.get("end_line", start + self.DEFAULT_WINDOW - 1))

        target = self._resolve_path(path_str, runtime)
        if target is None:
            return self._fail_escape()

        if not target.exists():
            return ToolResult.fail(f"File not found: {path_str}", is_runtime_error=True)

        if not target.is_file():
            return ToolResult.fail(f"Not a file: {path_str}", is_runtime_error=True)

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return self.exception_observation(e)

        lines = content.splitlines()
        total = len(lines)

        if start > total:
            return ToolResult.fail(f"start_line {start} exceeds file length {total}")

        end = min(end, total)
        selected = lines[start - 1:end]

        # 加行号
        numbered = [f"{i + start:4d}\t{line}" for i, line in enumerate(selected)]
        body = "\n".join(numbered)
        header = f"# {path_str} (lines {start}-{end} of {total})\n\n"

        truncated = end < total
        footer = "\n... (more lines below)" if truncated else ""

        return ToolResult.ok(
            header + body + footer,
            truncated=truncated,
            summary=f"Read {path_str}:{start}-{end}",
        )