"""Typed, non-streaming lifecycle events emitted by the AgentLoop."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, TypeAlias

ImmutableValue: TypeAlias = (
    Mapping[str, "ImmutableValue"]
    | tuple["ImmutableValue", ...]
    | str
    | int
    | float
    | bool
    | None
)


def _freeze(value: Any) -> ImmutableValue:
    """Recursively copy common payloads into immutable values."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, Enum):
        return _freeze(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    raise TypeError(f"unsupported immutable event value: {type(value).__name__}")


def _freeze_arguments(value: Any) -> Mapping[str, ImmutableValue]:
    """Freeze a tool-call argument mapping with a precise public type."""
    frozen = _freeze(value)
    if isinstance(frozen, Mapping):
        return frozen
    return MappingProxyType({})


@dataclass(frozen=True, kw_only=True)
class ToolCallSnapshot:
    """Immutable public view of a model tool call."""

    id: str
    name: str
    arguments: Mapping[str, ImmutableValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", _freeze_arguments(self.arguments))


@dataclass(frozen=True, kw_only=True)
class ModelResponseSnapshot:
    """Immutable model response payload for observers."""

    content: str = ""
    tool_calls: tuple[ToolCallSnapshot, ...] = ()
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_response(cls, response: Any) -> ModelResponseSnapshot:
        calls = tuple(
            ToolCallSnapshot(
                id=str(getattr(call, "id", "")),
                name=str(getattr(call, "name", "")),
                arguments=_freeze_arguments(getattr(call, "arguments", {})),
            )
            for call in getattr(response, "tool_calls", ())
        )
        usage = getattr(response, "usage", None)
        return cls(
            content=str(getattr(response, "content", "") or ""),
            tool_calls=calls,
            finish_reason=str(getattr(response, "finish_reason", "") or ""),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )


@dataclass(frozen=True, kw_only=True)
class ToolResultSnapshot:
    """Immutable tool result payload for observers."""

    success: bool
    content: str
    error: str = ""
    truncated: bool = False
    is_validation_failure: bool = False
    is_runtime_error: bool = False
    is_timeout: bool = False
    summary: str = ""

    @classmethod
    def from_result(cls, result: Any) -> ToolResultSnapshot:
        return cls(
            success=bool(getattr(result, "success", False)),
            content=str(getattr(result, "content", "") or ""),
            error=str(getattr(result, "error", "") or ""),
            truncated=bool(getattr(result, "truncated", False)),
            is_validation_failure=bool(getattr(result, "is_validation_failure", False)),
            is_runtime_error=bool(getattr(result, "is_runtime_error", False)),
            is_timeout=bool(getattr(result, "is_timeout", False)),
            summary=str(getattr(result, "summary", "") or ""),
        )


@dataclass(frozen=True, kw_only=True)
class BaseEvent:
    """Base lifecycle event.

    ``sequence`` is assigned by :class:`EventEmitter`; callers should leave it
    at zero when constructing an event. It is the authoritative ordering key.
    """

    run_id: str
    sequence: int = 0
    timestamp: float = 0.0
    event_type: ClassVar[str] = "event"

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            object.__setattr__(self, "timestamp", time.time())


@dataclass(frozen=True, kw_only=True)
class RunStarted(BaseEvent):
    event_type: ClassVar[str] = "run_started"
    session_id: str = ""
    task: str = ""
    workspace: str = ""


@dataclass(frozen=True, kw_only=True)
class RunStateSnapshot:
    """Immutable terminal state shared by terminal run events."""

    status: str = ""
    reason: str = ""
    summary: str = ""
    validation: str = ""
    validation_skipped_reason: str = ""
    reply: str = ""
    steps: int = 0
    total_tokens: int = 0
    modified_files: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "modified_files", tuple(self.modified_files))
        object.__setattr__(self, "findings", tuple(self.findings))


@dataclass(frozen=True, kw_only=True)
class RunFinished(BaseEvent):
    event_type: ClassVar[str] = "run_finished"
    session_id: str = ""
    final_state: RunStateSnapshot = RunStateSnapshot()

    @property
    def status(self) -> str:
        """Compatibility view for callers that used the pre-snapshot field."""
        return self.final_state.status

    @property
    def reason(self) -> str:
        """Compatibility view for callers that used the pre-snapshot field."""
        return self.final_state.reason


@dataclass(frozen=True, kw_only=True)
class RunFailed(BaseEvent):
    event_type: ClassVar[str] = "run_failed"
    session_id: str = ""
    error_type: str = ""
    error: str = ""
    final_state: RunStateSnapshot = RunStateSnapshot()


@dataclass(frozen=True, kw_only=True)
class TurnStarted(BaseEvent):
    event_type: ClassVar[str] = "turn_started"
    turn: int = 0


@dataclass(frozen=True, kw_only=True)
class TurnEnded(BaseEvent):
    event_type: ClassVar[str] = "turn_ended"
    turn: int = 0
    status: str = ""


@dataclass(frozen=True, kw_only=True)
class FeedbackRecorded(BaseEvent):
    event_type: ClassVar[str] = "feedback_recorded"
    step: int = 0
    kind: str = ""
    content: str = ""


@dataclass(frozen=True, kw_only=True)
class ValidationCompleted(BaseEvent):
    event_type: ClassVar[str] = "validation_completed"
    step: int = 0
    command: str = ""
    is_validation: bool = True
    passed: bool | None = None
    summary: str = ""
    is_runtime_error: bool = False


@dataclass(frozen=True, kw_only=True)
class AssistantReplied(BaseEvent):
    """A complete assistant response that answers without tool execution."""

    event_type: ClassVar[str] = "assistant_replied"
    turn: int = 0
    step: int = 0
    text: str = ""
    final_state: RunStateSnapshot = RunStateSnapshot()


    def __post_init__(self) -> None:
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class FinishAccepted(BaseEvent):
    event_type: ClassVar[str] = "finish_accepted"
    turn: int = 0
    step: int = 0
    summary: str = ""
    validation: str = ""
    notes: str = ""
    validation_skipped_reason: str = ""
    final_state: RunStateSnapshot = RunStateSnapshot()


@dataclass(frozen=True, kw_only=True)
class ModelStarted(BaseEvent):
    event_type: ClassVar[str] = "model_started"
    turn: int = 0
    step: int = 0
    model: str = ""


@dataclass(frozen=True, kw_only=True)
class ModelCompleted(BaseEvent):
    event_type: ClassVar[str] = "model_completed"
    turn: int = 0
    step: int = 0
    model: str = ""
    response: ModelResponseSnapshot | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.response is not None and not isinstance(self.response, ModelResponseSnapshot):
            object.__setattr__(self, "response", ModelResponseSnapshot.from_response(self.response))


@dataclass(frozen=True, kw_only=True)
class ModelFailed(BaseEvent):
    event_type: ClassVar[str] = "model_failed"
    turn: int = 0
    step: int = 0
    model: str = ""
    error_type: str = ""
    error: str = ""


@dataclass(frozen=True, kw_only=True)
class ToolStarted(BaseEvent):
    event_type: ClassVar[str] = "tool_started"
    turn: int = 0
    step: int = 0
    tool_name: str = ""
    action_id: str = ""
    arguments: Mapping[str, ImmutableValue] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.arguments is not None:
            object.__setattr__(self, "arguments", _freeze_arguments(self.arguments))


@dataclass(frozen=True, kw_only=True)
class ToolCompleted(BaseEvent):
    event_type: ClassVar[str] = "tool_completed"
    turn: int = 0
    step: int = 0
    tool_name: str = ""
    action_id: str = ""
    arguments: Mapping[str, ImmutableValue] | None = None
    args_hash: str = ""
    result: ToolResultSnapshot | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.arguments is not None:
            object.__setattr__(self, "arguments", _freeze_arguments(self.arguments))
        if self.result is not None:
            object.__setattr__(self, "result", ToolResultSnapshot.from_result(self.result))


@dataclass(frozen=True, kw_only=True)
class ToolFailed(BaseEvent):
    event_type: ClassVar[str] = "tool_failed"
    turn: int = 0
    step: int = 0
    tool_name: str = ""
    action_id: str = ""
    arguments: Mapping[str, ImmutableValue] | None = None
    args_hash: str = ""
    error_type: str = ""
    error: str = ""
    result: ToolResultSnapshot | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.arguments is not None:
            object.__setattr__(self, "arguments", _freeze_arguments(self.arguments))
        if self.result is not None:
            object.__setattr__(self, "result", ToolResultSnapshot.from_result(self.result))


AgentEvent: TypeAlias = (
    RunStarted
    | RunFinished
    | RunFailed
    | FeedbackRecorded
    | ValidationCompleted
    | AssistantReplied
    | FinishAccepted
    | TurnStarted
    | TurnEnded
    | ModelStarted
    | ModelCompleted
    | ModelFailed
    | ToolStarted
    | ToolCompleted
    | ToolFailed
)

__all__ = [
    "AgentEvent",
    "BaseEvent",
    "AssistantReplied",
    "FeedbackRecorded",
    "FinishAccepted",
    "ModelCompleted",
    "ModelFailed",
    "ModelResponseSnapshot",
    "ModelStarted",
    "RunFailed",
    "RunFinished",
    "RunStarted",
    "RunStateSnapshot",
    "ToolCallSnapshot",
    "ToolCompleted",
    "ToolFailed",
    "ToolResultSnapshot",
    "ToolStarted",
    "TurnEnded",
    "TurnStarted",
    "ValidationCompleted",
]
