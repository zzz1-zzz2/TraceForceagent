"""Typed, non-streaming lifecycle events emitted by the AgentLoop."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, ClassVar


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
    task: str = ""
    workspace: str = ""


@dataclass(frozen=True, kw_only=True)
class RunFinished(BaseEvent):
    event_type: ClassVar[str] = "run_finished"
    status: str = ""
    reason: str = ""


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
class ModelStarted(BaseEvent):
    event_type: ClassVar[str] = "model_started"
    turn: int = 0
    model: str = ""


@dataclass(frozen=True, kw_only=True)
class ModelCompleted(BaseEvent):
    event_type: ClassVar[str] = "model_completed"
    turn: int = 0
    model: str = ""
    response: Any = None


@dataclass(frozen=True, kw_only=True)
class ToolStarted(BaseEvent):
    event_type: ClassVar[str] = "tool_started"
    turn: int = 0
    tool_name: str = ""
    action_id: str = ""
    arguments: dict[str, Any] | None = None


@dataclass(frozen=True, kw_only=True)
class ToolCompleted(BaseEvent):
    event_type: ClassVar[str] = "tool_completed"
    turn: int = 0
    tool_name: str = ""
    action_id: str = ""
    result: Any = None


AgentEvent = (
    RunStarted
    | RunFinished
    | TurnStarted
    | TurnEnded
    | ModelStarted
    | ModelCompleted
    | ToolStarted
    | ToolCompleted
)

__all__ = [
    "AgentEvent",
    "BaseEvent",
    "ModelCompleted",
    "ModelStarted",
    "RunFinished",
    "RunStarted",
    "ToolCompleted",
    "ToolStarted",
    "TurnEnded",
    "TurnStarted",
]
