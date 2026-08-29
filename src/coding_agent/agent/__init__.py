"""Agent 子模块：loop、state、termination、brief。"""

from coding_agent.agent.brief import TaskBrief, TaskMode
from coding_agent.agent.loop import AgentRunResult, run
from coding_agent.agent.state import AgentState, StopReason
from coding_agent.agent.termination import TerminationController
from coding_agent.emitter import EventCollector, EventEmitter
from coding_agent.events import BaseEvent

__all__ = [
    "AgentState",
    "StopReason",
    "TaskBrief",
    "TaskMode",
    "run",
    "AgentRunResult",
    "TerminationController",
    "BaseEvent",
    "EventCollector",
    "EventEmitter",
]
