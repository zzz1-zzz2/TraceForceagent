"""Pure reducer tests for the TUI event bridge."""

from __future__ import annotations

import pytest

from coding_agent.events import (
    AssistantReplied,
    FinishAccepted,
    ModelCompleted,
    ModelDelta,
    ModelResponseSnapshot,
    ModelStarted,
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
    ToolCompleted,
    ToolFailed,
    ToolResultSnapshot,
    ToolStarted,
    TurnEnded,
    TurnStarted,
    ValidationCompleted,
)
from coding_agent.tui.state import (
    ToolUiStatus,
    initial_ui_state,
    reduce_event,
)


def _started(run_id: str, sequence: int = 1, task: str = "t") -> RunStarted:
    return RunStarted(run_id=run_id, sequence=sequence, task=task, workspace="/tmp/w")


def _turn_started(run_id: str, sequence: int, turn: int) -> TurnStarted:
    return TurnStarted(run_id=run_id, sequence=sequence, turn=turn)


def _turn_ended(run_id: str, sequence: int, turn: int, status: str) -> TurnEnded:
    return TurnEnded(run_id=run_id, sequence=sequence, turn=turn, status=status)


def _model_started(run_id: str, sequence: int, turn: int, model: str = "fake") -> ModelStarted:
    return ModelStarted(run_id=run_id, sequence=sequence, turn=turn, step=0, model=model)


def _model_completed(
    run_id: str,
    sequence: int,
    turn: int,
    content: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> ModelCompleted:
    return ModelCompleted(
        run_id=run_id,
        sequence=sequence,
        turn=turn,
        step=0,
        model="fake",
        response=ModelResponseSnapshot(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


def _tool_started(
    run_id: str,
    sequence: int,
    action_id: str,
    tool_name: str = "run_command",
    arguments: dict | None = None,
    turn: int = 1,
) -> ToolStarted:
    return ToolStarted(
        run_id=run_id,
        sequence=sequence,
        turn=turn,
        step=0,
        tool_name=tool_name,
        action_id=action_id,
        arguments=arguments or {},
    )


def _tool_completed(
    run_id: str,
    sequence: int,
    action_id: str,
    *,
    success: bool,
    content: str = "",
    error: str = "",
    is_validation_failure: bool = False,
    is_runtime_error: bool = False,
    tool_name: str = "run_command",
) -> ToolCompleted:
    return ToolCompleted(
        run_id=run_id,
        sequence=sequence,
        turn=1,
        step=0,
        tool_name=tool_name,
        action_id=action_id,
        arguments={},
        args_hash="hash",
        result=ToolResultSnapshot(
            success=success,
            content=content,
            error=error,
            is_validation_failure=is_validation_failure,
            is_runtime_error=is_runtime_error,
        ),
    )


def _tool_failed(
    run_id: str,
    sequence: int,
    action_id: str,
    *,
    error: str = "boom",
    content: str = "",
    tool_name: str = "run_command",
) -> ToolFailed:
    return ToolFailed(
        run_id=run_id,
        sequence=sequence,
        turn=1,
        step=0,
        tool_name=tool_name,
        action_id=action_id,
        arguments={},
        args_hash="hash",
        error_type="RuntimeError",
        error=error,
        result=ToolResultSnapshot(
            success=False,
            content=content,
            error=error,
            is_runtime_error=True,
        ),
    )


def _validation(
    run_id: str,
    sequence: int,
    *,
    passed: bool,
    summary: str = "1 passed",
    is_runtime_error: bool = False,
) -> ValidationCompleted:
    return ValidationCompleted(
        run_id=run_id,
        sequence=sequence,
        step=1,
        command="pytest -q",
        is_validation=True,
        passed=passed,
        summary=summary,
        is_runtime_error=is_runtime_error,
    )


def _finish_accepted(
    run_id: str,
    sequence: int,
    *,
    summary: str = "done",
    validation: str = "pytest -q",
) -> FinishAccepted:
    return FinishAccepted(
        run_id=run_id,
        sequence=sequence,
        turn=1,
        step=1,
        summary=summary,
        validation=validation,
        final_state=RunStateSnapshot(
            status="COMPLETED",
            reason="finish",
            summary=summary,
            validation=validation,
            steps=2,
            total_tokens=10,
            modified_files=("a.py",),
        ),
    )


def _run_finished(run_id: str, sequence: int) -> RunFinished:
    return RunFinished(
        run_id=run_id,
        sequence=sequence,
        final_state=RunStateSnapshot(
            status="COMPLETED",
            reason="finish",
            summary="done",
            validation="pytest -q",
            steps=2,
            total_tokens=10,
            modified_files=("a.py",),
        ),
    )


def _run_failed(run_id: str, sequence: int, error: str = "broken") -> RunFailed:
    return RunFailed(
        run_id=run_id,
        sequence=sequence,
        error_type="RuntimeError",
        error=error,
        final_state=RunStateSnapshot(
            status="ERROR",
            reason="RuntimeError",
            steps=1,
            total_tokens=2,
        ),
    )


def test_initial_state_is_empty_and_immutable():
    state = initial_ui_state()
    assert state.run_id == ""
    assert state.phase == "idle"
    assert state.tools == {}
    with pytest.raises((AttributeError, TypeError)):
        state.phase = "thinking"  # type: ignore[misc]
    with pytest.raises(TypeError):
        state.tools["run", "a1"] = None  # type: ignore[index]


def test_run_started_replaces_or_initialises_state():
    empty = initial_ui_state()
    state = reduce_event(empty, _started("run-1", sequence=1))
    assert state.run_id == "run-1"
    assert state.phase == "starting"
    assert state.last_sequence == 1
    assert state.last_event_type == "run_started"


def test_events_from_a_different_run_are_ignored_while_active():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _turn_started("run-1", sequence=2, turn=1))
    same_state = reduce_event(state, _turn_started("run-2", sequence=99, turn=7))
    assert same_state is state
    assert same_state.last_sequence == 2


def test_new_run_after_terminal_state_is_accepted():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _run_finished("run-1", sequence=2))
    assert state.terminal
    new_state = reduce_event(state, _started("run-2", sequence=1))
    assert new_state.run_id == "run-2"
    assert new_state.phase == "starting"
    assert new_state.last_sequence == 1
    assert not new_state.terminal


def test_sequence_duplicates_and_out_of_order_events_are_dropped():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=3))
    same = reduce_event(state, _turn_started("run-1", sequence=2, turn=1))
    assert same is state
    stale = reduce_event(state, _turn_started("run-1", sequence=3, turn=1))
    assert stale is state


def test_tool_started_then_completed_updates_existing_card():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _turn_started("run-1", sequence=2, turn=1))
    state = reduce_event(state, _model_started("run-1", sequence=3, turn=1))
    state = reduce_event(state, _model_completed("run-1", sequence=4, turn=1, input_tokens=3, output_tokens=5))
    state = reduce_event(
        state,
        _tool_started("run-1", sequence=5, action_id="a1", arguments={"command": "pytest"}),
    )
    tool = state.tools[("run-1", "a1")]
    assert tool.status is ToolUiStatus.RUNNING
    assert tool.sequence_started == 5
    state = reduce_event(
        state,
        _tool_completed(
            "run-1",
            sequence=6,
            action_id="a1",
            success=False,
            content="1 failed",
            error="exit 1",
            is_validation_failure=True,
        ),
    )
    tool = state.tools[("run-1", "a1")]
    assert tool.status is ToolUiStatus.ERROR
    assert tool.success is False
    assert tool.is_validation_failure is True
    assert tool.sequence_started == 5
    assert tool.sequence_completed == 6


def test_tool_completed_with_success_is_success_status_even_if_validation_failed():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _tool_started("run-1", sequence=2, action_id="a1"))
    state = reduce_event(
        state,
        _tool_completed("run-1", sequence=3, action_id="a1", success=True, content="ok"),
    )
    tool = state.tools[("run-1", "a1")]
    assert tool.status is ToolUiStatus.SUCCESS


def test_tool_failed_event_is_always_error():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _tool_started("run-1", sequence=2, action_id="a1"))
    state = reduce_event(state, _tool_failed("run-1", sequence=3, action_id="a1"))
    tool = state.tools[("run-1", "a1")]
    assert tool.status is ToolUiStatus.ERROR


def test_orphan_tool_completed_without_started_still_creates_a_card():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(
        state,
        _tool_completed("run-1", sequence=2, action_id="orphan", success=True, content="ok"),
    )
    tool = state.tools[("run-1", "orphan")]
    assert tool is not None
    assert tool.status is ToolUiStatus.SUCCESS
    assert tool.sequence_started == 0


def test_validation_phase_records_latest_validation():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _validation("run-1", sequence=2, passed=True))
    assert state.validation is not None
    assert state.validation.passed is True
    assert state.phase == "validation"
    state = reduce_event(state, _validation("run-1", sequence=3, passed=False, summary="1 failed"))
    assert state.validation is not None
    assert state.validation.passed is False
    assert state.validation.summary == "1 failed"


def test_model_completed_strips_token_total_and_stores_assistant_text():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _model_completed("run-1", sequence=2, turn=1, content="hello"))
    assert state.assistant_messages == ("hello",)
    state = reduce_event(state, _model_completed("run-1", sequence=3, turn=1, input_tokens=4, output_tokens=6))
    assert state.total_tokens == 10
    assert state.input_tokens == 4
    assert state.output_tokens == 6


def test_streaming_deltas_accumulate_locally_without_deduplication():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, ModelDelta(run_id="run-1", sequence=2, turn=1, text="x"))
    state = reduce_event(state, ModelDelta(run_id="run-1", sequence=3, turn=1, text="x"))

    assert state.assistant_draft == "xx"
    assert state.assistant_messages == ("xx",)


def test_model_completed_replaces_streaming_draft_and_reply_does_not_duplicate():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, ModelDelta(run_id="run-1", sequence=2, turn=1, text="partial"))
    state = reduce_event(state, _model_completed("run-1", sequence=3, turn=1, content="complete"))
    state = reduce_event(state, AssistantReplied(
        run_id="run-1",
        sequence=4,
        turn=1,
        text="complete",
        final_state=RunStateSnapshot(status="COMPLETED", reason="assistant_reply"),
    ))

    assert state.assistant_messages == ("complete",)
    assert state.assistant_draft == ""


def test_streaming_draft_is_isolated_between_turns():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, ModelDelta(run_id="run-1", sequence=2, turn=1, text="first"))
    state = reduce_event(state, ModelDelta(run_id="run-1", sequence=3, turn=2, text="second"))

    assert state.assistant_messages == ("first", "second")
    assert state.assistant_draft == "second"
    assert state.assistant_draft_turn == 2


    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _tool_started("run-1", sequence=2, action_id="a1"))
    state = reduce_event(state, _tool_started("run-1", sequence=3, action_id="a2"))
    state = reduce_event(state, _run_failed("run-1", sequence=4, error="core boom"))
    a1 = state.tools[("run-1", "a1")]
    a2 = state.tools[("run-1", "a2")]
    assert a1.status is ToolUiStatus.ERROR
    assert a1.error == "core boom"
    assert a2.status is ToolUiStatus.ERROR


def test_run_cancelled_marks_terminal_without_error():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, RunCancelled(
        run_id="run-1",
        sequence=2,
        final_state=RunStateSnapshot(status="CANCELLED", reason="cancelled", steps=2),
    ))
    assert state.terminal
    assert state.phase == "cancelled"
    assert state.terminal_status == "CANCELLED"
    assert state.terminal_error == ""


def test_assistant_reply_is_terminal_and_preserves_text():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, AssistantReplied(
        run_id="run-1",
        sequence=2,
        turn=1,
        text="你好",
        final_state=RunStateSnapshot(
            status="COMPLETED", reason="assistant_reply", summary="你好"
        ),
    ))
    assert state.terminal
    assert state.phase == "answered"
    assert state.assistant_messages == ("你好",)
    assert state.final_summary == "你好"


    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _model_completed("run-1", sequence=2, turn=1, input_tokens=3, output_tokens=5))
    state = reduce_event(state, _finish_accepted("run-1", sequence=3))
    state = reduce_event(state, _run_finished("run-1", sequence=4))
    assert state.terminal is True
    assert state.phase == "finished"
    assert state.final_summary == "done"
    assert state.final_validation == "pytest -q"
    assert state.modified_files == ("a.py",)
    assert state.total_tokens == 10


def test_protected_stop_phase_is_stopped():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(
        state,
        RunFinished(
            run_id="run-1",
            sequence=2,
            final_state=RunStateSnapshot(status="STOPPED", reason="max_steps", steps=1, total_tokens=0),
        ),
    )
    assert state.terminal is True
    assert state.phase == "stopped"


def test_turn_ended_finished_phase_transitions_to_finishing():
    state = reduce_event(initial_ui_state(), _started("run-1", sequence=1))
    state = reduce_event(state, _turn_started("run-1", sequence=2, turn=1))
    state = reduce_event(state, _turn_ended("run-1", sequence=3, turn=1, status="finished"))
    assert state.phase == "finishing"


def test_reducer_is_pure_and_returns_new_snapshots():
    state_a = initial_ui_state()
    state_b = reduce_event(state_a, _started("run-1", sequence=1))
    assert state_a is not state_b
    assert state_a.last_sequence == 0
    assert state_b.last_sequence == 1
