"""Agent 子模块：loop、state、termination、brief。"""

from coding_agent.agent.state import AgentState, StopReason
from coding_agent.agent.brief import TaskBrief, TaskMode
from coding_agent.agent.loop import run, AgentRunResult
from coding_agent.agent.termination import TerminationController

__all__ = [
    "AgentState",
    "StopReason",
    "TaskBrief",
    "TaskMode",
    "run",
    "AgentRunResult",
    "TerminationController",
]