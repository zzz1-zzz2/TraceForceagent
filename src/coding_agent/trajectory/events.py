"""JSONL serialization and event-backed trajectory persistence."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from coding_agent.events import AgentEvent
from coding_agent.trajectory.logger import TrajectoryLogger

SCHEMA_VERSION = 2


class TrajectorySerializationError(TypeError):
    """Raised when an event contains a value outside the trajectory schema."""


def _to_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _to_json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if hasattr(value, "items"):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    raise TrajectorySerializationError(f"unsupported trajectory value: {type(value).__name__}")


def event_to_record(event: AgentEvent) -> dict[str, Any]:
    """Convert one typed event into a versioned, JSON-safe legacy-compatible record."""
    payload = _to_json_value(event)
    if not isinstance(payload, dict):
        raise TrajectorySerializationError("event did not serialize to an object")

    event_type = event.event_type
    payload["schema_version"] = SCHEMA_VERSION
    payload["event_type"] = event_type
    payload["type"] = event_type
    payload["run_id"] = event.run_id
    payload["sequence"] = event.sequence
    payload["timestamp"] = event.timestamp

    if event_type == "model_completed":
        response = payload.pop("response", {}) or {}
        payload["type"] = "model_call"
        payload["step"] = payload.get("step", 0)
        payload["input_tokens"] = response.get("input_tokens", 0)
        payload["output_tokens"] = response.get("output_tokens", 0)
        payload["tool_calls_count"] = len(response.get("tool_calls", ()))
    elif event_type in {"tool_completed", "tool_failed"}:
        result = payload.pop("result", None) or {}
        payload["type"] = "tool_call"
        payload["tool"] = payload.pop("tool_name", "")
        payload["args"] = payload.pop("arguments", {})
        payload["result_success"] = result.get("success", False)
        payload["result_content"] = result.get("content", "")[:1000]
        payload["result_error"] = result.get("error", "")
        payload["result_summary"] = result.get("summary", "")
        payload["is_validation_failure"] = result.get("is_validation_failure", False)
        payload["is_runtime_error"] = result.get("is_runtime_error", False)
        if event_type == "tool_failed":
            payload["error_msg"] = payload.get("error", "")
    elif event_type == "assistant_replied":
        final = payload.pop("final_state", {}) or {}
        payload["type"] = "assistant_reply"
        payload["reply"] = payload.pop("text", "")
        payload["step"] = payload.get("step", final.get("steps", 0))
        payload.update(_legacy_terminal_fields(final))
    elif event_type == "finish_accepted":
        final = payload.pop("final_state", {}) or {}
        payload["type"] = "finish"
        payload["step"] = payload.get("step", final.get("steps", 0))
        payload.update(_legacy_terminal_fields(final))
    elif event_type == "run_finished":
        payload.setdefault("session_id", "")
        final = payload.pop("final_state", {}) or {}
        payload["type"] = "stop" if final.get("status") == "STOPPED" else "run_finished"
        payload["step"] = final.get("steps", 0)
        payload.update(_legacy_terminal_fields(final))
    elif event_type == "run_failed":
        payload.setdefault("session_id", "")
        final = payload.pop("final_state", {}) or {}
        payload["type"] = "error"
        payload["step"] = final.get("steps", 0)
        payload["error_msg"] = payload.get("error", "")
        payload.update(_legacy_terminal_fields(final))
    elif event_type == "feedback_recorded":
        payload["type"] = "feedback"
    elif event_type == "validation_completed":
        payload["type"] = "validation"

    return payload


def _legacy_terminal_fields(final: dict[str, Any]) -> dict[str, Any]:
    """Flatten terminal state while retaining every old logger field."""
    return {
        "status": final.get("status", ""),
        "reason": final.get("reason", ""),
        "summary": final.get("summary", ""),
        "validation": final.get("validation", ""),
        "validation_skipped_reason": final.get("validation_skipped_reason", ""),
        "step": final.get("steps", 0),
        "total_steps": final.get("steps", 0),
        "total_tokens": final.get("total_tokens", 0),
        "modified_files": final.get("modified_files", []),
    }


class TrajectoryEventSink:
    """Critical synchronous subscriber that persists every lifecycle event."""

    critical = True

    def __init__(self, logger: TrajectoryLogger):
        self.logger = logger

    @property
    def path(self) -> Path:
        return self.logger.path

    def __call__(self, event: AgentEvent) -> None:
        record = event_to_record(event)
        self.logger.write_record(record)

    def close(self) -> None:
        self.logger.close()


__all__ = [
    "SCHEMA_VERSION",
    "TrajectoryEventSink",
    "TrajectorySerializationError",
    "event_to_record",
]
