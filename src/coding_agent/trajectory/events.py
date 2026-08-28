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
    """Convert one typed event into a versioned, JSON-safe record."""
    payload = _to_json_value(event)
    if not isinstance(payload, dict):
        raise TrajectorySerializationError("event did not serialize to an object")
    payload["schema_version"] = SCHEMA_VERSION
    payload["event_type"] = event.event_type
    # Keep the legacy discriminator so existing trajectory readers remain useful.
    payload["type"] = {
        "model_completed": "model_call",
        "tool_completed": "tool_call",
        "tool_failed": "tool_call",
        "feedback_recorded": "feedback",
        "finish_accepted": "finish",
        "run_finished": "stop" if payload.get("final_state", {}).get("status") == "STOPPED" else "finish",
        "run_failed": "error",
    }.get(event.event_type, event.event_type)
    payload["run_id"] = event.run_id
    payload["sequence"] = event.sequence
    payload["timestamp"] = event.timestamp
    if event.event_type in {"tool_completed", "tool_failed"}:
        result = payload.pop("result", None) or {}
        payload["tool"] = payload.pop("tool_name", "")
        payload["args"] = payload.pop("arguments", {})
        payload["result_success"] = result.get("success", False)
        payload["result_content"] = result.get("content", "")[:1000]
        payload["result_summary"] = result.get("summary", "")
        payload["is_validation_failure"] = result.get("is_validation_failure", False)
        payload["is_runtime_error"] = result.get("is_runtime_error", False)
    if event.event_type == "run_finished":
        final = payload.pop("final_state", {})
        payload.update({
            "status": final.get("status", ""),
            "reason": final.get("reason", ""),
            "total_steps": final.get("steps", 0),
            "total_tokens": final.get("total_tokens", 0),
            "modified_files": final.get("modified_files", []),
        })
    if event.event_type == "run_failed":
        final = payload.pop("final_state", {})
        payload.update({
            "status": final.get("status", "ERROR"),
            "reason": final.get("reason", ""),
            "total_steps": final.get("steps", 0),
            "total_tokens": final.get("total_tokens", 0),
            "modified_files": final.get("modified_files", []),
        })
    return payload


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
