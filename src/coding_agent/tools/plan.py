"""update_plan 工具：让 LLM 显式维护多步计划。"""

from __future__ import annotations

from coding_agent.model.types import ToolResult
from coding_agent.runtime.base import Runtime, ToolExecutionContext
from coding_agent.tools.base import Tool


class UpdatePlanTool(Tool):
    """LLM 主动维护多步任务计划。"""

    name = "update_plan"
    description = (
        "Update your plan for completing the task. Each item has status "
        "('pending' | 'in_progress' | 'completed') and content. Use this at the "
        "start of complex tasks and after major milestones."
    )
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "List of plan items",
                "items": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "'pending' | 'in_progress' | 'completed'",
                        },
                        "content": {
                            "type": "string",
                            "description": "What this step does",
                        },
                    },
                    "required": ["status", "content"],
                },
            },
        },
        "required": ["items"],
    }

    def execute(self, args: dict, runtime: Runtime, context: ToolExecutionContext | None = None) -> ToolResult:
        items = args.get("items", [])
        if not isinstance(items, list):
            return ToolResult.fail("items must be a list")

        lines = ["Plan updated:"]
        for it in items:
            status = it.get("status", "?")
            content = it.get("content", "")
            icon = {"pending": "☐", "in_progress": "▶", "completed": "☑"}.get(status, "?")
            lines.append(f"  {icon} [{status}] {content}")

        return ToolResult.ok("\n".join(lines), summary=f"Plan: {len(items)} items")