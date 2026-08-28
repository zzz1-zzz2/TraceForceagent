"""TrajectoryLogger：把 Agent 事件写入 JSONL。

P1-4：轨迹文件写到 ~/.traceforce/runs/<workspace-basename>/run_<id>/trajectory.jsonl,
不再写到 workspace/runs/,避免污染目标 repo。

可以通过 env `TRACE_ROOT=...` 或在构造时显式传 trace_root 来覆盖根目录。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _default_trace_root() -> Path:
    """默认 ~/.traceforce/runs/。"""
    return Path.home() / ".traceforce" / "runs"


class TrajectoryLogger:
    """Agent 事件审计日志。

    每个 event 至少包含：
    - event_id, step, timestamp, type
    - 额外字段按 type 不同而不同

    P1-4 路径布局：
        <trace_root>/<workspace_basename>/<run_id>/trajectory.jsonl

    其中 workspace_basename 用于把不同 repo 的 run 分开。
    """

    def __init__(
        self,
        run_id: str,
        workspace: Path,
        trace_root: Optional[Path] = None,
    ):
        self.run_id = run_id
        self.workspace = workspace
        root = trace_root or _default_trace_root()
        # 按 workspace 名字分桶,避免不同 repo 的 run 混在一个目录里
        ws_name = workspace.resolve().name or "default"
        self.run_dir = root / ws_name / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "trajectory.jsonl"
        self._file = self.path.open("a", encoding="utf-8")
        self._counter = 0

    def _write(self, event: dict[str, Any]) -> None:
        self._counter += 1
        event["event_id"] = self._counter
        event["timestamp"] = datetime.utcnow().isoformat()
        self._file.write(json.dumps(event, ensure_ascii=False, default=str))
        self._file.write("\n")
        self._file.flush()

    # ----- 各种事件类型 -----

    def record_model_call(self, state, response) -> None:
        """记录一次 LLM 调用。"""
        self._write({
            "run_id": self.run_id,
            "step": state.step_count,
            "type": "model_call",
            "model": getattr(response, "raw", {}).model if hasattr(response, "raw") and response.raw else "unknown",
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "tool_calls_count": len(response.tool_calls),
        })

    def record_tool_call(self, state, action, observation) -> None:
        """记录一次 tool call 与 observation。"""
        self._write({
            "run_id": self.run_id,
            "step": state.step_count,
            "type": "tool_call",
            "tool": action.tool_name,
            "action_id": action.action_id,
            "args": action.arguments,
            "args_hash": action.args_hash,
            "result_success": observation.success,
            "result_content": observation.content[:1000],  # 截断避免巨大
            "result_summary": observation.summary,
            "is_validation_failure": observation.is_validation_failure,
            "is_runtime_error": observation.is_runtime_error,
        })

    def record_feedback(self, state, content: str) -> None:
        """记录一条反馈（InvalidAction / FinishPolicy 拒绝等）。

        与 record_tool_call 的区别：
        - 没有真实的 tool dispatch
        - 内容是给模型看的反馈文本
        - step 不递增（feedback 不算真实推进）
        """
        self._write({
            "run_id": self.run_id,
            "step": state.step_count,
            "type": "feedback",
            "content": content[:1000],
        })

    def record_finish(self, state, action) -> None:
        """记录 finish。"""
        self._write({
            "run_id": self.run_id,
            "step": state.step_count,
            "type": "finish",
            "summary": action.summary,
            "validation": action.validation,
            "notes": action.notes,
            "validation_skipped_reason": action.validation_skipped_reason,
            "total_steps": state.step_count,
            "total_tokens": state.total_tokens(),
            "modified_files": sorted(state.modified_files),
        })

    def record_stop(self, state, reason: str) -> None:
        """记录保护性终止。"""
        self._write({
            "run_id": self.run_id,
            "step": state.step_count,
            "type": "stop",
            "reason": reason,
            "total_steps": state.step_count,
            "total_tokens": state.total_tokens(),
            "modified_files": sorted(state.modified_files),
            "status": state.status,
        })

    def record_error(self, state, error: Exception) -> None:
        """记录错误。"""
        self._write({
            "run_id": self.run_id,
            "step": state.step_count,
            "type": "error",
            "error_type": type(error).__name__,
            "error_msg": str(error),
        })

    def close(self) -> None:
        """关闭文件。"""
        try:
            self._file.close()
        except Exception:
            pass

    def __del__(self) -> None:
        self.close()