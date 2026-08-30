"""Immutable data types used by the in-memory agent session."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

MAX_MESSAGE_CONTENT_CHARS = 64_000
MAX_MESSAGE_FIELD_CHARS = 16_000
MAX_SNAPSHOT_FIELD_CHARS = 4_000
MAX_SNAPSHOT_ITEMS = 20
_MAX_NESTING = 8
_MAX_COLLECTION_ITEMS = 128


class SessionCapacityError(ValueError):
    """Raised when one immutable session payload exceeds its hard limit."""


class SessionStateError(RuntimeError):
    """Raised when a session operation does not match its current state."""


class SessionActiveError(SessionStateError):
    """Raised when an operation would conflict with the active run."""


def _bounded_text(value: Any, *, field: str, limit: int) -> str:
    text = str(value or "")
    if len(text) > limit:
        raise SessionCapacityError(
            f"{field} exceeds the session limit of {limit} characters"
        )
    return text


def _freeze(value: Any, *, field: str, depth: int = 0) -> Any:
    """Recursively copy a payload into immutable, bounded values."""
    if depth > _MAX_NESTING:
        raise SessionCapacityError(f"{field} exceeds the maximum nesting depth")
    if isinstance(value, Mapping):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise SessionCapacityError(
                f"{field} exceeds the limit of {_MAX_COLLECTION_ITEMS} items"
            )
        frozen = {
            str(key): _freeze(item, field=f"{field}.{key}", depth=depth + 1)
            for key, item in value.items()
        }
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple, set, frozenset)):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise SessionCapacityError(
                f"{field} exceeds the limit of {_MAX_COLLECTION_ITEMS} items"
            )
        return tuple(
            _freeze(item, field=f"{field}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        )
    if isinstance(value, str):
        return _bounded_text(value, field=field, limit=MAX_MESSAGE_FIELD_CHARS)
    if isinstance(value, (int, float, bool, type(None))):
        return value
    raise TypeError(f"unsupported session value for {field}: {type(value).__name__}")


def _freeze_mapping(value: Mapping[str, Any] | None, *, field: str) -> Mapping[str, Any]:
    frozen = _freeze(value or {}, field=field)
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return frozen


def _clip_snapshot_text(value: Any, *, field: str) -> str:
    text = str(value or "")
    return text[:MAX_SNAPSHOT_FIELD_CHARS]


@dataclass(frozen=True, slots=True)
class SessionMessage:
    """One immutable fact recorded in a session's complete history."""

    role: str
    content: str = ""
    run_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    tool_result: str = ""
    success: bool | None = None
    error: str = ""
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        role = _bounded_text(self.role, field="role", limit=64)
        if not role:
            raise ValueError("session message role cannot be empty")
        object.__setattr__(self, "role", role)
        object.__setattr__(
            self,
            "content",
            _bounded_text(self.content, field="content", limit=MAX_MESSAGE_CONTENT_CHARS),
        )
        object.__setattr__(self, "run_id", _bounded_text(self.run_id, field="run_id", limit=256))
        object.__setattr__(
            self,
            "tool_call_id",
            _bounded_text(self.tool_call_id, field="tool_call_id", limit=256),
        )
        object.__setattr__(
            self,
            "tool_name",
            _bounded_text(self.tool_name, field="tool_name", limit=256),
        )
        object.__setattr__(self, "arguments", _freeze_mapping(self.arguments, field="arguments"))
        object.__setattr__(
            self,
            "tool_result",
            _bounded_text(self.tool_result, field="tool_result", limit=MAX_MESSAGE_CONTENT_CHARS),
        )
        object.__setattr__(self, "error", _bounded_text(self.error, field="error", limit=MAX_MESSAGE_FIELD_CHARS))
        if self.timestamp == 0.0:
            object.__setattr__(self, "timestamp", time.time())

    @property
    def result_content(self) -> str:
        """Compatibility alias for callers that call tool output a result."""
        return self.tool_result


@dataclass(frozen=True, slots=True)
class PreviousRunSnapshot:
    """Bounded terminal summary exposed to the next run."""

    run_id: str
    outcome: str = ""
    reason: str = ""
    summary: str = ""
    validation: str = ""
    notes: str = ""
    validation_skipped_reason: str = ""
    error: str = ""
    modified_files: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    steps: int = 0
    total_tokens: int = 0
    status: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _bounded_text(self.run_id, field="run_id", limit=256))
        for name in (
            "outcome", "reason", "summary", "validation", "notes",
            "validation_skipped_reason", "error", "status",
        ):
            object.__setattr__(self, name, _clip_snapshot_text(getattr(self, name), field=name))
        object.__setattr__(
            self,
            "modified_files",
            tuple(_clip_snapshot_text(path, field="modified_files") for path in self.modified_files[:MAX_SNAPSHOT_ITEMS]),
        )
        object.__setattr__(
            self,
            "findings",
            tuple(_clip_snapshot_text(item, field="findings") for item in self.findings[:MAX_SNAPSHOT_ITEMS]),
        )

    @classmethod
    def from_facts(
        cls,
        run_id: str,
        facts: Any = None,
        *,
        outcome: str = "completed",
        reason: str = "",
        error: str = "",
    ) -> PreviousRunSnapshot:
        """Build a bounded snapshot from a result or terminal-state-like object."""
        source = facts
        final_state = getattr(source, "final_state", None)
        if final_state is not None:
            source = final_state
        return cls(
            run_id=run_id,
            outcome=outcome,
            reason=reason or getattr(facts, "stop_reason", "") or getattr(final_state, "reason", ""),
            summary=getattr(source, "summary", "") if source is not None else "",
            validation=getattr(source, "validation", "") if source is not None else "",
            notes=getattr(source, "notes", "") if source is not None else "",
            validation_skipped_reason=(
                getattr(source, "validation_skipped_reason", "")
                if source is not None else ""
            ),
            error=error,
            modified_files=tuple(getattr(source, "modified_files", ()) or ()) if source is not None else (),
            findings=tuple(getattr(source, "findings", ()) or ()) if source is not None else (),
            steps=int(getattr(source, "steps", 0) or getattr(facts, "steps", 0) or 0),
            total_tokens=int(getattr(source, "total_tokens", 0) or getattr(facts, "total_tokens", 0) or 0),
            status=str(getattr(source, "status", "") or ""),
        )


@dataclass(frozen=True, slots=True)
class SessionRun:
    """Stable handle and terminal record for one session run."""

    run_id: str
    task: str
    status: str = "active"
    started_at: float = 0.0
    ended_at: float | None = None
    snapshot: PreviousRunSnapshot | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _bounded_text(self.run_id, field="run_id", limit=256))
        object.__setattr__(self, "task", _bounded_text(self.task, field="task", limit=MAX_MESSAGE_CONTENT_CHARS))
        if self.started_at == 0.0:
            object.__setattr__(self, "started_at", time.time())


__all__ = [
    "MAX_MESSAGE_CONTENT_CHARS",
    "MAX_MESSAGE_FIELD_CHARS",
    "MAX_SNAPSHOT_FIELD_CHARS",
    "MAX_SNAPSHOT_ITEMS",
    "PreviousRunSnapshot",
    "SessionActiveError",
    "SessionCapacityError",
    "SessionMessage",
    "SessionRun",
    "SessionStateError",
]
