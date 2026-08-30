"""Pure Python UI state and lifecycle-event reducer.

The reducer deliberately has no Textual imports or widget side effects.  It is
fed immutable lifecycle events after they have crossed the worker-thread
boundary, and returns a new snapshot that the TUI may render.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType

from coding_agent.events import (
    AgentEvent,
    AssistantReplied,
    FeedbackRecorded,
    FinishAccepted,
    ModelCompleted,
    ModelDelta,
    ModelFailed,
    ModelStarted,
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
    TurnEnded,
    TurnStarted,
    ValidationCompleted,
)


class ToolUiStatus(StrEnum):
    """Presentation status for one logical tool action."""

    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


ToolKey = tuple[str, str]


@dataclass(frozen=True)
class ToolUiState:
    """Pure state for one ``(run_id, action_id)`` tool card."""

    run_id: str
    action_id: str
    tool_name: str = ""
    arguments: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    turn: int = 0
    step: int = 0
    status: ToolUiStatus = ToolUiStatus.RUNNING
    success: bool | None = None
    content: str = ""
    error: str = ""
    summary: str = ""
    truncated: bool = False
    is_validation_failure: bool = False
    is_runtime_error: bool = False
    sequence_started: int = 0
    sequence_completed: int = 0

    @property
    def key(self) -> ToolKey:
        """Return the stable identity used to update this card in place."""
        return (self.run_id, self.action_id)


@dataclass(frozen=True)
class ValidationUiState:
    """Latest validation result shown by the UI."""

    step: int
    command: str
    is_validation: bool
    passed: bool | None
    summary: str
    is_runtime_error: bool
    sequence: int


@dataclass(frozen=True)
class RunUiState:
    """Reducer-owned state for one run, independent of Textual widgets."""

    run_id: str = ""
    last_sequence: int = 0
    last_event_type: str = ""
    phase: str = "idle"
    turn: int = 0
    step: int = 0
    model: str = ""
    model_running: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_calls: int = 0
    tools: Mapping[ToolKey, ToolUiState] = field(default_factory=lambda: MappingProxyType({}))
    validation: ValidationUiState | None = None
    feedback: tuple[str, ...] = ()
    assistant_messages: tuple[str, ...] = ()
    finish_accepted: bool = False
    final_summary: str = ""
    final_validation: str = ""
    final_notes: str = ""
    validation_skipped_reason: str = ""
    terminal: bool = False
    terminal_status: str = ""
    terminal_reason: str = ""
    terminal_error: str = ""
    modified_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", MappingProxyType(dict(self.tools)))


def initial_ui_state(run_id: str = "") -> RunUiState:
    """Create an empty UI state, optionally scoped to a known run."""
    return RunUiState(run_id=run_id)


def reduce_event(state: RunUiState, event: AgentEvent) -> RunUiState:
    """Apply one sequenced lifecycle event without mutating ``state``.

    Events from another run are ignored unless they are a new ``RunStarted``;
    this permits a single app to start a fresh run while preventing late
    messages from the previous worker from corrupting the new transcript.
    Duplicate and out-of-order events are ignored using the emitter-assigned
    sequence number. Unassigned sequence ``0`` is intentionally ignored.
    """
    if event.run_id != state.run_id:
        # A new run may replace an empty or already-terminal state. While a
        # run is active, a late event from another worker must be ignored.
        if not isinstance(event, RunStarted) or (state.run_id and not state.terminal):
            return state
        state = initial_ui_state(event.run_id)

    if event.sequence <= state.last_sequence:
        return state

    next_state = _reduce_current_run(state, event)
    return replace(
        next_state,
        last_sequence=event.sequence,
        last_event_type=event.event_type,
    )


def _reduce_current_run(state: RunUiState, event: AgentEvent) -> RunUiState:
    if isinstance(event, RunStarted):
        return replace(
            state,
            phase="starting",
            terminal=False,
            terminal_status="",
            terminal_reason="",
            terminal_error="",
            turn=0,
            step=0,
            model="",
            model_running=False,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            model_calls=0,
            tools={},
            validation=None,
            feedback=(),
            assistant_messages=(),
            finish_accepted=False,
            final_summary="",
            final_validation="",
            final_notes="",
            validation_skipped_reason="",
            modified_files=(),
        )

    if isinstance(event, TurnStarted):
        return replace(state, phase="thinking", turn=event.turn, model_running=False)

    if isinstance(event, ModelStarted):
        return replace(
            state,
            phase="thinking",
            turn=event.turn,
            step=event.step,
            model=event.model,
            model_running=True,
            model_calls=state.model_calls + 1,
        )

    if isinstance(event, ModelDelta):
        assistant_messages = state.assistant_messages
        if assistant_messages:
            assistant_messages = (*assistant_messages[:-1], event.accumulated_text)
        elif event.accumulated_text:
            assistant_messages = (event.accumulated_text,)
        return replace(
            state,
            phase="thinking",
            turn=event.turn,
            step=event.step,
            model=event.model or state.model,
            model_running=True,
            assistant_messages=assistant_messages,
        )

    if isinstance(event, ModelCompleted):
        response = event.response
        content = response.content if response is not None else ""
        assistant_messages = state.assistant_messages
        if content.strip():
            assistant_messages = (*assistant_messages, content)
        return replace(
            state,
            phase="thinking",
            turn=event.turn,
            step=event.step,
            model=event.model or state.model,
            model_running=False,
            input_tokens=state.input_tokens + (response.input_tokens if response else 0),
            output_tokens=state.output_tokens + (response.output_tokens if response else 0),
            total_tokens=state.total_tokens + (
                (response.input_tokens + response.output_tokens) if response else 0
            ),
            assistant_messages=assistant_messages,
        )

    if isinstance(event, ModelFailed):
        return replace(
            state,
            phase="error",
            turn=event.turn,
            step=event.step,
            model=event.model or state.model,
            model_running=False,
            terminal_error=event.error or event.error_type,
        )

    if isinstance(event, ToolStarted):
        key = (event.run_id, event.action_id)
        tools = dict(state.tools)
        previous = tools.get(key)
        tools[key] = ToolUiState(
            run_id=event.run_id,
            action_id=event.action_id,
            tool_name=event.tool_name or (previous.tool_name if previous else ""),
            arguments=_copy_arguments(event.arguments or (previous.arguments if previous else {})),
            turn=event.turn,
            step=event.step,
            status=ToolUiStatus.RUNNING,
            sequence_started=event.sequence,
        )
        return replace(state, phase="working", turn=event.turn, step=event.step, tools=tools)

    if isinstance(event, (ToolCompleted, ToolFailed)):
        return _reduce_tool_terminal(state, event)

    if isinstance(event, ValidationCompleted):
        validation = ValidationUiState(
            step=event.step,
            command=event.command,
            is_validation=event.is_validation,
            passed=event.passed,
            summary=event.summary,
            is_runtime_error=event.is_runtime_error,
            sequence=event.sequence,
        )
        return replace(state, phase="validation", step=event.step, validation=validation)

    if isinstance(event, FeedbackRecorded):
        feedback = (*state.feedback, event.content)
        return replace(state, phase="feedback", step=event.step, feedback=feedback[-10:])

    if isinstance(event, AssistantReplied):
        final = event.final_state
        return replace(
            state,
            phase="answered",
            turn=event.turn,
            step=event.step,
            assistant_messages=(*state.assistant_messages, event.text),
            terminal_status=final.status,
            terminal_reason=final.reason,
            final_summary=final.summary,
            terminal=True,
            modified_files=tuple(final.modified_files),
        )

    if isinstance(event, FinishAccepted):
        final = event.final_state
        return replace(
            state,
            phase="finishing",
            turn=event.turn,
            step=event.step,
            finish_accepted=True,
            final_summary=event.summary,
            final_validation=event.validation,
            final_notes=event.notes,
            validation_skipped_reason=event.validation_skipped_reason,
            terminal_status=final.status,
            terminal_reason=final.reason,
            modified_files=tuple(final.modified_files),
        )

    if isinstance(event, TurnEnded):
        if event.status == "error":
            phase = "error"
        elif event.status in {"finished", "stopped"}:
            phase = "finishing"
        else:
            phase = "idle"
        return replace(state, phase=phase, turn=event.turn, model_running=False)

    if isinstance(event, RunCancelled):
        final = event.final_state
        tools = {
            key: replace(tool, status=ToolUiStatus.CANCELLED)
            if tool.status is ToolUiStatus.RUNNING else tool
            for key, tool in state.tools.items()
        }
        return replace(
            state,
            phase="cancelled",
            step=final.steps,
            total_tokens=final.total_tokens,
            model_running=False,
            tools=tools,
            terminal=True,
            terminal_status="CANCELLED",
            terminal_reason=final.reason or "cancelled",
            final_summary=final.summary or state.final_summary,
            final_validation=final.validation or state.final_validation,
            final_notes=final.notes or state.final_notes,
            validation_skipped_reason=final.validation_skipped_reason or state.validation_skipped_reason,
            modified_files=tuple(final.modified_files),
        )

    if isinstance(event, RunFinished):
        final = event.final_state
        phase = "stopped" if final.status == "STOPPED" else ("answered" if final.reason == "assistant_reply" else "finished")
        return replace(
            state,
            phase=phase,
            step=final.steps,
            total_tokens=final.total_tokens,
            input_tokens=state.input_tokens,
            output_tokens=state.output_tokens,
            model_running=False,
            terminal=True,
            terminal_status=final.status,
            terminal_reason=final.reason,
            final_summary=final.summary or state.final_summary,
            final_validation=final.validation or state.final_validation,
            final_notes=state.final_notes,
            validation_skipped_reason=final.validation_skipped_reason or state.validation_skipped_reason,
            modified_files=tuple(final.modified_files),
        )

    if isinstance(event, RunFailed):
        final = event.final_state
        tools = {
            key: replace(tool, status=ToolUiStatus.ERROR, error=tool.error or event.error)
            if tool.status is ToolUiStatus.RUNNING
            else tool
            for key, tool in state.tools.items()
        }
        return replace(
            state,
            phase="error",
            step=final.steps,
            model_running=False,
            tools=tools,
            terminal=True,
            terminal_status=final.status or "ERROR",
            terminal_reason=final.reason,
            terminal_error=event.error or event.error_type,
            final_summary=final.summary or state.final_summary,
            final_validation=final.validation or state.final_validation,
            final_notes=state.final_notes,
            validation_skipped_reason=final.validation_skipped_reason or state.validation_skipped_reason,
            modified_files=tuple(final.modified_files),
        )

    return state


def _reduce_tool_terminal(
    state: RunUiState,
    event: ToolCompleted | ToolFailed,
) -> RunUiState:
    key = (event.run_id, event.action_id)
    tools = dict(state.tools)
    previous = tools.get(key)
    result = event.result
    success = result.success if result is not None else False
    status = (
        ToolUiStatus.ERROR
        if isinstance(event, ToolFailed) or not success
        else ToolUiStatus.SUCCESS
    )
    error = (
        event.error
        if isinstance(event, ToolFailed)
        else (result.error if result is not None else "")
    )
    tools[key] = ToolUiState(
        run_id=event.run_id,
        action_id=event.action_id,
        tool_name=event.tool_name or (previous.tool_name if previous else ""),
        arguments=_copy_arguments(event.arguments or (previous.arguments if previous else {})),
        turn=event.turn,
        step=event.step,
        status=status,
        success=success,
        content=result.content if result is not None else "",
        error=error,
        summary=result.summary if result is not None else "",
        truncated=result.truncated if result is not None else False,
        is_validation_failure=result.is_validation_failure if result is not None else False,
        is_runtime_error=result.is_runtime_error if result is not None else False,
        sequence_started=previous.sequence_started if previous else 0,
        sequence_completed=event.sequence,
    )
    return replace(state, phase="working", turn=event.turn, step=event.step, tools=tools)


def _copy_arguments(arguments: Mapping[str, object]) -> Mapping[str, object]:
    """Copy event arguments so later reducer callers cannot mutate a snapshot."""
    return MappingProxyType(dict(arguments))


__all__ = [
    "RunUiState",
    "ToolKey",
    "ToolUiState",
    "ToolUiStatus",
    "ValidationUiState",
    "initial_ui_state",
    "reduce_event",
]
