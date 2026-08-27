"""ContextManager：构造 Active Context。

五段式：
1. System Prompt
2. Original Task（P0，永远保留）
3. Task Brief（P1）
4. Working State（P1）
5. Recent Interaction（P2，可淘汰）

Full Trajectory 由 TrajectoryLogger 单独保存，与 Active Context 解耦。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from coding_agent.agent.brief import TaskBrief
from coding_agent.agent.state import AgentState
from coding_agent.config import AgentConfig
from coding_agent.context.working_state import WorkingStateBuilder
from coding_agent.model.types import ToolResult


@dataclass
class _RecentTurn:
    """一对 (assistant, tool_result) 称为一个 turn。"""

    assistant_content: str
    tool_call_id: str
    tool_call_name: str
    tool_call_args: dict
    tool_result_content: str
    tool_result_success: bool


class ContextManager:
    """管理 Active Context 的构造与裁剪。"""

    SYSTEM_PROMPT = """You are a coding agent. You autonomously complete software engineering tasks.

You have access to these tools:
- list_files(path, max_depth): browse directory structure
- read_file(path, start_line, end_line): read file content (default 200-line window)
- search_code(query, path, max_results): search for symbols/text using ripgrep
- apply_patch(path, old_string, new_string) OR apply_patch(path, content, mode="create"): modify/create/delete files
- run_command(command, cwd, timeout): execute shell command (independent subprocess, no persistent shell)
- git_diff(): show current changes
- update_plan(items): maintain your multi-step plan (visible in TUI)
- finish(summary, validation, notes): explicitly submit your work when done

Rules:
1. Read existing code before modifying it.
2. Run tests after every change to verify.
3. Use apply_patch with surgical edits, not full-file overwrites.
4. Don't repeat the same action without new information — if stuck, change strategy.
5. Always call finish() when done, with summary + validation. Don't end with just text.

Workspace path boundary: You cannot escape the workspace directory."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.working_state_builder = WorkingStateBuilder()
        self._recent_turns: deque[_RecentTurn] = deque(maxlen=config.recent_turns * 2)

    def build(self, state: AgentState, brief: TaskBrief) -> list[dict[str, Any]]:
        """构造完整 Active Context messages。"""
        messages: list[dict[str, Any]] = []

        # 1. System Prompt（P0）
        messages.append({"role": "system", "content": self.SYSTEM_PROMPT})

        # 2. Original Task（P0，永远保留）
        messages.append({"role": "user", "content": f"# Task\n{state.original_task}"})

        # 3. Task Brief（P1）
        messages.append({"role": "assistant", "content": brief.to_text()})

        # 4. Working State（P1，每次都重新生成）
        working_text = self.working_state_builder.render(state)
        if working_text != "(no state yet)":
            messages.append({"role": "user", "content": working_text})

        # 5. Recent Interaction（P2/P3，可淘汰）
        for turn in list(self._recent_turns)[-self.config.recent_turns:]:
            # Assistant tool call（OpenAI 格式）
            messages.append({
                "role": "assistant",
                "content": turn.assistant_content or "",
                "tool_calls": [
                    {
                        "id": turn.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": turn.tool_call_name,
                            "arguments": _json_dumps(turn.tool_call_args),
                        },
                    }
                ],
            })
            # Tool result
            messages.append({
                "role": "tool",
                "tool_call_id": turn.tool_call_id,
                "content": turn.tool_result_content,
            })

        return messages

    def record_observation(
        self,
        state: AgentState,
        action,  # ToolAction
        observation: ToolResult,
    ) -> None:
        """记录一个 turn 到 Recent Interaction。"""
        self._recent_turns.append(_RecentTurn(
            assistant_content="",
            tool_call_id=action.action_id or "",
            tool_call_name=action.tool_name,
            tool_call_args=action.arguments,
            tool_result_content=observation.content[: self.config.max_tool_output],
            tool_result_success=observation.success,
        ))


def _json_dumps(obj: Any) -> str:
    """安全 JSON dump。"""
    import json

    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"