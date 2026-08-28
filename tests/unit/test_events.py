"""P2-1A typed event and synchronous emitter tests."""

import pytest

from coding_agent.agent.loop import run
from coding_agent.config import AgentConfig
from coding_agent.emitter import EventCollector, EventEmitter
from coding_agent.events import (
    FinishAccepted,
    ModelCompleted,
    ModelFailed,
    ModelResponseSnapshot,
    ModelStarted,
    RunFailed,
    RunFinished,
    RunStarted,
    ToolCompleted,
    ToolResultSnapshot,
    ToolStarted,
    TurnEnded,
    TurnStarted,
    ValidationCompleted,
)
from coding_agent.model.client import ModelClient
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall, ToolResult


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
        ValidationCompleted,
        TurnEnded,
        TurnStarted, ModelStarted, ModelCompleted, FinishAccepted, TurnEnded,
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


def test_event_payloads_are_snapshots_not_core_objects():
    response = _response(
        "apply_patch",
        {"path": "app.py", "options": {"mode": "create"}},
        "call-1",
    )
    result = ToolResult(success=True, content="ok")
    model_event = ModelCompleted(run_id="r", turn=1, response=response)
    started_event = ToolStarted(
        run_id="r", turn=1, tool_name="apply_patch", arguments=response.tool_calls[0].arguments
    )
    completed_event = ToolCompleted(run_id="r", turn=1, tool_name="apply_patch", result=result)

    response.content = "mutated"
    response.tool_calls[0].arguments["path"] = "other.py"
    result.content = "mutated"

    assert isinstance(model_event.response, ModelResponseSnapshot)
    assert model_event.response.content == ""
    assert model_event.response.tool_calls[0].arguments["path"] == "app.py"
    assert started_event.arguments["options"] == {"mode": "create"}
    assert isinstance(completed_event.result, ToolResultSnapshot)
    assert completed_event.result.content == "ok"

    with pytest.raises(TypeError):
        started_event.arguments["path"] = "other.py"
    with pytest.raises(TypeError):
        model_event.response.tool_calls[0].arguments["path"] = "other.py"


def test_model_exception_emits_failure_terminal_events(monkeypatch, tmp_path):
    class FailingModel:
        model = "failing"

        def generate(self, messages, tools=None):
            raise RuntimeError("model unavailable")

    def fake_from_config(cls, config):
        return FailingModel()

    monkeypatch.setattr(ModelClient, "from_config", classmethod(fake_from_config))
    collector = EventCollector()
    config = AgentConfig(
        workspace_root=tmp_path,
        trace_root=tmp_path / "trace",
        max_wall_time=30,
    )
    emitter = EventEmitter()
    emitter.subscribe(collector)

    with pytest.raises(RuntimeError, match="model unavailable"):
        run("test model failure", tmp_path, config, emitter=emitter)

    assert [type(event) for event in collector.events] == [
        RunStarted,
        TurnStarted,
        ModelStarted,
        ModelFailed,
        TurnEnded,
        RunFailed,
    ]
    assert collector.events[4].status == "error"
    assert collector.events[-1].error_type == "RuntimeError"
    assert all(not isinstance(event, RunFinished) for event in collector.events)


def test_protected_stop_emits_run_finished_without_open_turn(monkeypatch, tmp_path):
    class FakeModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return _response("list_files", {"path": ".", "max_depth": 1}, "call")

    def fake_from_config(cls, config):
        return FakeModel()

    monkeypatch.setattr(ModelClient, "from_config", classmethod(fake_from_config))
    collector = EventCollector()
    config = AgentConfig(
        workspace_root=tmp_path,
        trace_root=tmp_path / "trace",
        max_steps=1,
        max_model_calls=5,
        max_wall_time=30,
    )
    emitter = EventEmitter()
    emitter.subscribe(collector)

    result = run("inspect", tmp_path, config, emitter=emitter)

    assert result.stop_reason == "max_steps"
    assert isinstance(collector.events[-1], RunFinished)
    assert collector.events[-1].status == "STOPPED"
    assert [event.turn for event in collector.events if isinstance(event, TurnStarted)] == [1]


def test_parser_exception_closes_turn_and_run(monkeypatch, tmp_path):
    class FakeModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return _response("list_files", {"path": ".", "max_depth": 1}, "call")

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: FakeModel()))
    monkeypatch.setattr(
        "coding_agent.model.parsers.openai_compatible.OpenAICompatibleParser.parse",
        lambda self, response: (_ for _ in ()).throw(ValueError("malformed response")),
    )
    collector = EventCollector()
    config = AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace")
    emitter = EventEmitter()
    emitter.subscribe(collector)

    with pytest.raises(ValueError, match="malformed response"):
        run("inspect", tmp_path, config, emitter=emitter)

    assert [type(event) for event in collector.events] == [
        RunStarted, TurnStarted, ModelStarted, ModelCompleted, TurnEnded, RunFailed,
    ]
    assert collector.events[-2].status == "error"


def test_context_exception_closes_turn_and_run(monkeypatch, tmp_path):
    class FakeModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return _response("list_files", {"path": ".", "max_depth": 1}, "call")

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: FakeModel()))
    monkeypatch.setattr(
        "coding_agent.context.manager.ContextManager.build",
        lambda self, state, brief: (_ for _ in ()).throw(OSError("context unavailable")),
    )
    collector = EventCollector()
    config = AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace")
    emitter = EventEmitter()
    emitter.subscribe(collector)

    with pytest.raises(OSError, match="context unavailable"):
        run("inspect", tmp_path, config, emitter=emitter)

    assert [type(event) for event in collector.events] == [
        RunStarted, TurnStarted, TurnEnded, RunFailed,
    ]
    assert collector.events[-2].status == "error"


def test_finish_policy_exception_closes_turn_and_run(monkeypatch, tmp_path):
    class FakeModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return _response("finish", {"summary": "done", "validation": "passed"}, "call")

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: FakeModel()))
    monkeypatch.setattr(
        "coding_agent.agent.loop.FinishPolicy.check",
        lambda self, state, action: (_ for _ in ()).throw(RuntimeError("policy unavailable")),
    )
    collector = EventCollector()
    config = AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace")
    emitter = EventEmitter()
    emitter.subscribe(collector)

    with pytest.raises(RuntimeError, match="policy unavailable"):
        run("finish task", tmp_path, config, emitter=emitter)

    assert [type(event) for event in collector.events] == [
        RunStarted, TurnStarted, ModelStarted, ModelCompleted, TurnEnded, RunFailed,
    ]
    assert collector.events[-2].status == "error"


def test_run_finished_critical_failure_hides_success_from_ui(monkeypatch, tmp_path):
    collector = EventCollector()

    class FakeModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return _response("list_files", {"path": ".", "max_depth": 1}, "call")

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: FakeModel()))

    def fail_only_on_success(event):
        if event.event_type == "run_finished":
            raise OSError("terminal sink unavailable")

    config = AgentConfig(
        workspace_root=tmp_path,
        trace_root=tmp_path / "trace",
        max_steps=1,
    )
    emitter = EventEmitter()
    emitter.subscribe(collector)
    emitter.subscribe(fail_only_on_success, critical=True)

    with pytest.raises(Exception, match="terminal sink unavailable"):
        run("inspect", tmp_path, config, emitter=emitter)

    event_types = [event.event_type for event in collector.events]
    assert "run_finished" not in event_types
    assert event_types[-1] == "run_failed"
    assert not any(event.event_type == "run_finished" for event in collector.events)
