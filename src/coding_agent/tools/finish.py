"""finish 工具：显式任务完成。"""

from __future__ import annotations

from coding_agent.model.types import ToolResult
from coding_agent.runtime.base import Runtime
from coding_agent.tools.base import Tool


class FinishTool(Tool):
    """显式提交任务结果。"""

    name = "finish"
    description = (
        "Submit your work as complete. Provide a summary of what you did and "
        "how you verified it. Use this when the task is done."
    )
    schema = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Concise summary of changes made",
            },
            "validation": {
                "type": "string",
                "description": "How you verified the changes (e.g. 'pytest passed: 5/5')",
            },
            "notes": {
                "type": "string",
                "description": "Optional: known limitations or follow-ups",
            },
        },
        "required": ["summary"],
    }

    def execute(self, args: dict, runtime: Runtime) -> ToolResult:
        # finish tool 不真正"执行"，只是触发 AgentLoop 的 finish 处理
        # 实际 finish 逻辑在 AgentLoop.run() 里
        summary = args.get("summary", "")
        validation = args.get("validation", "")

        return ToolResult.ok(
            f"Task finished.\nSummary: {summary}\nValidation: {validation}",
            summary=f"Finish: {summary[:100]}",
        )