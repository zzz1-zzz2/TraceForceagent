"""Cooperative cancellation contract and lifecycle regressions."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from coding_agent.agent.cancellation import CancellationRequested, CancellationToken
from coding_agent.agent.loop import run
from coding_agent.config import AgentConfig
from coding_agent.emitter import EventCollector, EventEmitter
from coding_agent.events import RunCancelled, RunStarted, ValidationCompleted
from coding_agent.model.client import ModelClient
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall, ToolResult
from coding_agent.session import AgentSession
from coding_agent.tools.filesystem import ListFilesTool
from coding_agent.tools.shell import RunCommandTool


def _config(workspace: Path) -> AgentConfig:
    return AgentConfig(
        workspace_root=workspace,
        trace_root=workspace / "trace",
        max_steps=5,
        max_model_calls=5,
        max_wall_time=30,
    )


def test_token_is_idempotent_and_raises() -> None:
    token = CancellationToken()
    assert token.is_cancelled is False
    assert token.cancel() is True
    assert token.cancel() is False
    assert token.is_cancelled is True
    with pytest.raises(CancellationRequested):
        token.raise_if_cancelled()


def test_token_concurrent_cancel_has_one_winner() -> None:
    token = CancellationToken()
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def cancel() -> None:
        barrier.wait()
        results.append(token.cancel())

    threads = [threading.Thread(target=cancel) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False] * 7 + [True]
    assert token.is_cancelled


def test_session_cancelled_terminal_event_and_snapshot(tmp_path: Path, monkeypatch) -> None:
    class NeverCalled:
        model = "fake"

        def generate(self, messages, tools=None):
            raise AssertionError("cancelled run must not call model")

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: NeverCalled()))
    token = CancellationToken()
    token.cancel()
    collector = EventCollector()
    emitter = EventEmitter()
    emitter.subscribe(collector)
    session = AgentSession(tmp_path)
    result = run("cancel me", tmp_path, _config(tmp_path), emitter=emitter, session=session, cancellation_token=token)

    assert result.stop_reason == "cancelled"
    assert [type(event) for event in collector.events] == [RunStarted, RunCancelled]
    assert collector.events[-1].final_state.status == "CANCELLED"
    assert session.active_run is None
    assert session.runs[-1].status == "cancelled"
    assert session.snapshot is not None
    assert session.snapshot.outcome == "cancelled"


def test_cancel_after_model_return_preserves_tokens_and_closes_run(tmp_path: Path, monkeypatch) -> None:
    token = CancellationToken()

    class CancellingModel:
        model = "fake"

        def generate(self, messages, tools=None):
            token.cancel()
            return ModelResponse(content="late", usage=TokenUsage(input_tokens=2, output_tokens=3))

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: CancellingModel()))
    collector = EventCollector()
    emitter = EventEmitter()
    emitter.subscribe(collector)
    session = AgentSession(tmp_path)
    result = run("cancel after model", tmp_path, _config(tmp_path), emitter=emitter, session=session, cancellation_token=token)

    assert result.stop_reason == "cancelled"
    assert result.total_tokens == 5
    assert session.active_run is None
    assert [event.event_type for event in collector.events].count("run_cancelled") == 1
    assert not any(event.event_type == "run_failed" for event in collector.events)


def test_cancel_after_tool_return_pairs_session_facts(tmp_path: Path, monkeypatch) -> None:
    token = CancellationToken()

    class ToolModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return ModelResponse(
                tool_calls=[ToolCall(id="call-1", name="list_files", arguments={"path": ".", "max_depth": 1})],
                finish_reason="tool_calls",
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: ToolModel()))
    original_execute = ListFilesTool.execute

    def execute_then_cancel(self, args, runtime):
        result = original_execute(self, args, runtime)
        token.cancel()
        return result

    monkeypatch.setattr(ListFilesTool, "execute", execute_then_cancel)
    session = AgentSession(tmp_path)
    result = run("cancel after tool", tmp_path, _config(tmp_path), session=session, cancellation_token=token)

    assert result.stop_reason == "cancelled"
    assert session.active_run is None
    facts = session.messages
    calls = [fact for fact in facts if fact.tool_call_id == "call-1" and fact.role == "assistant"]
    results = [fact for fact in facts if fact.tool_call_id == "call-1" and fact.role == "tool"]
    assert len(calls) == len(results) == 1


def test_cancel_after_validation_classification_preserves_validation_fact(
    tmp_path: Path, monkeypatch
) -> None:
    """A completed validation remains observable when cancellation is already set."""
    token = CancellationToken()

    class ToolModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return ModelResponse(
                tool_calls=[ToolCall(
                    id="call-validation",
                    name="run_command",
                    arguments={"command": "python -m pytest -q"},
                )],
                finish_reason="tool_calls",
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: ToolModel()))

    def execute_then_cancel(self, args, runtime):
        result = ToolResult.ok(
            "$ python -m pytest -q\n\n1 passed",
            summary="Command OK (0.0s)",
        )
        token.cancel()
        return result

    monkeypatch.setattr(RunCommandTool, "execute", execute_then_cancel)
    collector = EventCollector()
    emitter = EventEmitter()
    emitter.subscribe(collector)
    session = AgentSession(tmp_path)

    result = run(
        "run validation",
        tmp_path,
        _config(tmp_path),
        emitter=emitter,
        session=session,
        cancellation_token=token,
    )

    assert result.stop_reason == "cancelled"
    event_types = [event.event_type for event in collector.events]
    assert event_types.count("run_cancelled") == 1
    assert "run_finished" not in event_types
    assert "run_failed" not in event_types
    validation_index = event_types.index("validation_completed")
    cancelled_index = event_types.index("run_cancelled")
    assert validation_index < cancelled_index
    validation = collector.events[validation_index]
    assert isinstance(validation, ValidationCompleted)
    assert validation.command == "python -m pytest -q"
    assert validation.passed is True
    assert session.active_run is None

    facts = session.messages
    assert [
        (fact.role, fact.tool_call_id, fact.tool_name)
        for fact in facts
        if fact.tool_call_id == "call-validation"
    ] == [
        ("assistant", "call-validation", "run_command"),
        ("tool", "call-validation", "run_command"),
    ]

    assert result.trajectory_path is not None
    records = [
        json.loads(line)
        for line in result.trajectory_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    trajectory_types = [record["event_type"] for record in records]
    assert "validation_completed" in trajectory_types
    assert trajectory_types[-1] == "run_cancelled"
    assert trajectory_types.index("validation_completed") < trajectory_types.index("run_cancelled")


def test_cancelled_session_can_continue_next_run(tmp_path: Path, monkeypatch) -> None:
    token = CancellationToken()

    class CancelModel:
        model = "fake"

        def generate(self, messages, tools=None):
            token.cancel()
            return ModelResponse(content="ignored", usage=TokenUsage())

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: CancelModel()))
    session = AgentSession(tmp_path)
    first = run("stop this", tmp_path, _config(tmp_path), session=session, cancellation_token=token)
    assert first.stop_reason == "cancelled"

    class ReplyModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return ModelResponse(content="continued", finish_reason="stop", usage=TokenUsage())

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: ReplyModel()))
    second = run("continue", tmp_path, _config(tmp_path), session=session)
    assert second.reply == "continued"
    assert session.active_run is None
    assert len(session.runs) == 2
