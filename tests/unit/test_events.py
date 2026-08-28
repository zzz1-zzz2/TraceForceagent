"""P2-1A typed event and synchronous emitter tests."""

from pathlib import Path

from coding_agent.agent.loop import run
from coding_agent.config import AgentConfig
from coding_agent.emitter import EventCollector, EventEmitter
from coding_agent.events import (
    ModelCompleted,
    ModelStarted,
    RunFinished,
    RunStarted,
    ToolCompleted,
    ToolStarted,
    TurnEnded,
    TurnStarted,
)
from coding_agent.model.client import ModelClient
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall


def _response(name, arguments, call_id):
    return ModelResponse(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=1, output_tokens=1),
    )


def test_emitter_assigns_monotonic_sequence_and_isolates_sink_errors():
    collector = EventCollector()
    seen = []

    def failing_sink(_event):
        raise RuntimeError("sink failed")

    emitter = EventEmitter()
    emitter.subscribe(failing_sink)
    emitter.subscribe(collector)
    emitter.subscribe(lambda event: seen.append(event.event_type))

    first = emitter.emit(RunStarted(run_id="r", task="t"))
    second = emitter.emit(TurnStarted(run_id="r", turn=1))

    assert [event.sequence for event in collector.events] == [1, 2]
    assert first.sequence < second.sequence
    assert seen == ["run_started", "turn_started"]


def test_agent_loop_emits_lifecycle_order(monkeypatch, tmp_path):
    responses = iter([
        _response("apply_patch", {"path": "hello.py", "mode": "create", "content": "x = 1\n"}, "a1"),
        _response("run_command", {"command": "python3 -m py_compile hello.py"}, "a2"),
        _response("finish", {"summary": "done", "validation": "compile passed"}, "a3"),
    ])

    class FakeModel:
        model = "fake"

        def generate(self, messages, tools=None):
            try:
                return next(responses)
            except StopIteration:
                return _response("finish", {"summary": "fallback", "validation": ""}, "fallback")

    def fake_from_config(cls, config):
        return FakeModel()

    monkeypatch.setattr(ModelClient, "from_config", classmethod(fake_from_config))
    collector = EventCollector()
    config = AgentConfig(
        context_budget=8000,
        recent_turns=4,
        max_steps=10,
        max_model_calls=10,
        max_wall_time=30,
        command_timeout=10,
        workspace_root=tmp_path,
        trace_root=tmp_path / "trace",
    )

    emitter = EventEmitter()
    emitter.subscribe(collector)
    result = run("create a file", tmp_path, config, emitter=emitter)
    assert result.stop_reason == "finish"

    assert [type(event) for event in collector.events] == [
        RunStarted,
        TurnStarted, ModelStarted, ModelCompleted, ToolStarted, ToolCompleted,
        TurnEnded,
        TurnStarted, ModelStarted, ModelCompleted, ToolStarted, ToolCompleted,
        TurnEnded,
        TurnStarted, ModelStarted, ModelCompleted, TurnEnded,
        RunFinished,
    ]
    sequences = [event.sequence for event in collector.events]
    assert sequences == list(range(1, len(sequences) + 1))

    # Collector remains independently useful for asserting a canonical turn.
    collector.clear()
    for event in [
        RunStarted(run_id="r"), TurnStarted(run_id="r", turn=1),
        ModelStarted(run_id="r", turn=1), ModelCompleted(run_id="r", turn=1),
        ToolStarted(run_id="r", turn=1), ToolCompleted(run_id="r", turn=1),
        TurnEnded(run_id="r", turn=1), RunFinished(run_id="r"),
    ]:
        emitter.emit(event)
    assert [type(event) for event in collector.events] == [
        RunStarted, TurnStarted, ModelStarted, ModelCompleted,
        ToolStarted, ToolCompleted, TurnEnded, RunFinished,
    ]
