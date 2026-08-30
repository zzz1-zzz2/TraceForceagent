"""Trajectory event serialization and critical sink tests."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from coding_agent.emitter import CriticalEventDeliveryError, EventCollector, EventEmitter
from coding_agent.events import (
    AssistantReplied,
    FinishAccepted,
    ModelDelta,
    RunCancelled,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
    ToolCompleted,
    ToolResultSnapshot,
)
from coding_agent.trajectory import (
    SCHEMA_VERSION,
    TrajectoryEventSink,
    TrajectoryLogger,
    TrajectorySerializationError,
    event_to_record,
)


def test_event_to_record_is_json_safe_and_preserves_identity():
    event = ToolCompleted(
        run_id="run-1",
        sequence=7,
        timestamp=12.5,
        turn=2,
        tool_name="run_command",
        action_id="a1",
        arguments={"path": Path("src/app.py"), "flags": ["-q"]},
        args_hash="abc123",
        result=ToolResultSnapshot(
            success=False,
            content="x" * 2000,
            error="failed",
            is_validation_failure=True,
            summary="1 failed",
        ),
    )

    record = event_to_record(event)
    json.dumps(record)
    assert record["schema_version"] == SCHEMA_VERSION
    assert record["event_type"] == "tool_completed"
    assert record["type"] == "tool_call"
    assert record["run_id"] == "run-1"
    assert record["sequence"] == 7
    assert record["timestamp"] == 12.5
    assert record["step"] == 0
    assert record["args"]["path"] == "src/app.py"
    assert len(record["result_content"]) == 1000
    assert record["is_validation_failure"] is True


@dataclass
class Unsupported:
    value: object


def test_event_to_record_rejects_unknown_values():
    event = FinishAccepted(run_id="r", notes=Unsupported(object()))  # type: ignore[arg-type]
    with pytest.raises(TrajectorySerializationError):
        event_to_record(event)


def test_assistant_reply_serializes_as_distinct_terminal_record():
    record = event_to_record(AssistantReplied(
        run_id="r",
        sequence=3,
        turn=1,
        text="你好",
        final_state=RunStateSnapshot(
            status="COMPLETED", reason="assistant_reply", summary="你好"
        ),
    ))
    assert record["event_type"] == "assistant_replied"
    assert record["type"] == "assistant_reply"
    assert record["reply"] == "你好"
    assert record["reason"] == "assistant_reply"


def test_run_finished_serializes_terminal_record():
    record = event_to_record(RunFinished(
        run_id="r",
        sequence=3,
        final_state=RunStateSnapshot(
            status="COMPLETED",
            reason="finish",
            summary="done",
            validation="pytest -q",
            steps=2,
            total_tokens=9,
            modified_files=("b.py", "a.py"),
        ),
    ))
    assert record["type"] == "run_finished"
    assert record["status"] == "COMPLETED"
    assert record["step"] == 2
    assert record["total_steps"] == 2
    assert record["modified_files"] == ["b.py", "a.py"]
    json.dumps(record)


def test_run_cancelled_serializes_terminal_record():
    record = event_to_record(RunCancelled(
        run_id="r",
        sequence=3,
        session_id="s",
        final_state=RunStateSnapshot(
            status="CANCELLED",
            reason="cancelled",
            summary="stopped safely",
            steps=2,
            total_tokens=9,
        ),
    ))
    assert record["event_type"] == "run_cancelled"
    assert record["type"] == "cancelled"
    assert record["status"] == "CANCELLED"
    assert record["reason"] == "cancelled"
    assert record["summary"] == "stopped safely"
    assert record["step"] == 2
    json.dumps(record)


def test_trajectory_sink_writes_one_record_per_event(tmp_path):
    logger = TrajectoryLogger("r", tmp_path / "workspace", tmp_path / "trace")
    sink = TrajectoryEventSink(logger)
    emitter = EventEmitter()
    emitter.subscribe(sink, critical=True)
    collector = EventCollector()
    emitter.subscribe(collector)
    emitter.emit(FinishAccepted(run_id="r", sequence=0, summary="done"))
    sink.close()

    lines = [line for line in sink.path.read_text().splitlines() if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["sequence"] == 1
    assert record["event_type"] == "finish_accepted"
    assert len(collector.events) == 1


def test_trajectory_sink_excludes_transient_deltas_but_keeps_observer_stream(tmp_path):
    logger = TrajectoryLogger("r", tmp_path / "workspace", tmp_path / "trace")
    sink = TrajectoryEventSink(logger)
    emitter = EventEmitter()
    emitter.subscribe(sink, critical=True)
    collector = EventCollector()
    emitter.subscribe(collector)

    for index in range(1000):
        emitter.emit(ModelDelta(run_id="r", turn=1, text=f"fragment-{index}"))
    emitter.emit(FinishAccepted(run_id="r", summary="done"))
    sink.close()

    assert sum(isinstance(event, ModelDelta) for event in collector.events) == 1000
    records = [json.loads(line) for line in sink.path.read_text().splitlines() if line]
    assert len(records) == 1
    assert records[0]["event_type"] == "finish_accepted"
    assert records[0]["sequence"] == 1001


    seen = []

    def broken(_event):
        raise OSError("disk full")

    emitter = EventEmitter()
    emitter.subscribe(broken, critical=True)
    emitter.subscribe(lambda event: seen.append(event.event_type))

    with pytest.raises(CriticalEventDeliveryError, match="disk full"):
        emitter.emit(RunStarted(run_id="r"))
    # The healthy sibling still observed an ordinary event.
    assert seen == ["run_started"]

    # The broken sink is skipped on later events; healthy sinks remain usable.
    emitter.emit(RunStarted(run_id="r"))
    assert seen == ["run_started", "run_started"]


def test_finish_accepted_critical_failure_is_hidden_from_ui():
    seen = []

    def broken(_event):
        raise OSError("disk full")

    emitter = EventEmitter()
    emitter.subscribe(broken, critical=True)
    emitter.subscribe(lambda event: seen.append(event.event_type))

    with pytest.raises(CriticalEventDeliveryError, match="disk full"):
        emitter.emit(FinishAccepted(run_id="r"))
    assert seen == []


def test_finish_accepted_reaches_ui_after_persistence():
    seen = []
    order = []

    def persistent(event):
        order.append(("trajectory", event.event_type))

    def ui(event):
        order.append(("ui", event.event_type))
        seen.append(event.event_type)

    emitter = EventEmitter()
    emitter.subscribe(ui)
    emitter.subscribe(persistent, critical=True)
    emitter.emit(FinishAccepted(run_id="r"))

    assert seen == ["finish_accepted"]
    assert order == [("trajectory", "finish_accepted"), ("ui", "finish_accepted")]
