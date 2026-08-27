"""apply_patch 工具：创建/修改/删除文件。

支持三种模式：
1. modify: 用 old_string/new_string 做精确替换
2. create: 直接写入新文件
3. delete: 删除文件
"""

from __future__ import annotations

import os
from pathlib import Path

from coding_agent.model.types import ToolResult
from coding_agent.runtime.base import Runtime
from coding_agent.tools.base import Tool


class ApplyPatchTool(Tool):
    """修改、创建、删除文件。"""

    name = "apply_patch"
    description = (
        "Apply a change to a file. Modes: "
        "'modify' (replace old_string with new_string), "
        "'create' (write content to a new file), "
        "'delete' (remove a file)."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to workspace",
            },
            "mode": {
                "type": "string",
                "description": "'modify' | 'create' | 'delete'",
                "default": "modify",
            },
            "old_string": {
                "type": "string",
                "description": "For modify: exact string to replace (must match exactly once)",
            },
            "new_string": {
                "type": "string",
                "description": "For modify: replacement string; for create: full file content",
            },
            "content": {
                "type": "string",
                "description": "Alias for new_string in create mode",
            },
        },
        "required": ["path"],
    }

    def execute(self, args: dict, runtime: Runtime) -> ToolResult:
        path_str = args.get("path", "")
        if not path_str:
            return ToolResult.fail("Missing required parameter: path")

        mode = args.get("mode", "modify")
        if mode not in ("modify", "create", "delete"):
            return ToolResult.fail(
                f"Invalid mode: {mode}. Must be 'modify', 'create', or 'delete'."
            )

        # resolve path
        try:
            workspace = runtime.workspace.resolve()
            target = (workspace / path_str).resolve()
            target.relative_to(workspace)  # boundary check
        except (ValueError, Exception):
            return ToolResult.fail("Path escapes workspace boundary", is_runtime_error=True)

        if mode == "create":
            return self._create(target, workspace, path_str, args)
        elif mode == "delete":
            return self._delete(target, path_str)
        else:  # modify
            return self._modify(target, path_str, args)

    def _create(self, target: Path, workspace: Path, path_str: str, args: dict) -> ToolResult:
        content = args.get("new_string") or args.get("content", "")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # 原子写：先写 .tmp，再 rename
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(target)
        except Exception as e:
            return self.exception_observation(e)

        rel = target.relative_to(workspace)
        return ToolResult.ok(
            f"Created {rel}\n({len(content)} bytes)",
            summary=f"Created {path_str}",
        )

    def _delete(self, target: Path, path_str: str) -> ToolResult:
        if not target.exists():
            return ToolResult.fail(f"File not found: {path_str}", is_runtime_error=True)
        try:
            target.unlink()
        except Exception as e:
            return self.exception_observation(e)
        return ToolResult.ok(f"Deleted {path_str}", summary=f"Deleted {path_str}")

    def _modify(self, target: Path, path_str: str, args: dict) -> ToolResult:
        if not target.exists():
            return ToolResult.fail(f"File not found: {path_str}", is_runtime_error=True)

        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")

        if not old_string:
            return ToolResult.fail("modify mode requires 'old_string'")

        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            return self.exception_observation(e)

        count = content.count(old_string)
        if count == 0:
            return ToolResult.fail(
                f"old_string not found in {path_str}. "
                f"Make sure it matches exactly (including whitespace).",
                is_runtime_error=True,
            )
        if count > 1:
            return ToolResult.fail(
                f"old_string matches {count} times in {path_str}. "
                f"Provide more context to make it unique.",
                is_runtime_error=True,
            )

        new_content = content.replace(old_string, new_string, 1)

        try:
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(new_content, encoding="utf-8")
            tmp.replace(target)
        except Exception as e:
            return self.exception_observation(e)

        return ToolResult.ok(
            f"Modified {path_str}\n({len(new_content)} bytes total)",
            summary=f"Modified {path_str}",
        )