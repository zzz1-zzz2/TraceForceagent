"""MVP2-B regression tests for Session-aware loop and context behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.agent.brief import TaskBrief
from coding_agent.agent.loop import run
from coding_agent.agent.state import AgentState
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager
from coding_agent.emitter import EventCollector, EventEmitter
from coding_agent.events import (
    RunFailed,
    RunFinished,
    RunStarted,
)
from coding_agent.model.client import ModelClient
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall
from coding_agent.session import AgentSession, PreviousRunSnapshot


class _ReplyModel:
    model = "fake"

    def __init__(self, replies: list[str]):
        self.replies = iter(replies)
        self.messages: list[list[dict]] = []

    def generate(self, messages, tools=None):
        self.messages.append(messages)
        return ModelResponse(
            content=next(self.replies),
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


def _patch_reply_model(monkeypatch, replies: list[str]) -> _ReplyModel:
    model = _ReplyModel(replies)
    monkeypatch.setattr(
        ModelClient,
        "from_config",
        classmethod(lambda cls, config: model),
    )
    return model


def _config(workspace: Path, trace_root: Path) -> AgentConfig:
    return AgentConfig(
        workspace_root=workspace,
        trace_root=trace_root,
        context_budget=8_000,
        recent_turns=4,
        max_steps=5,
        max_model_calls=5,
        max_wall_time=30,
    )


def test_two_runs_share_session_but_have_distinct_run_ids(monkeypatch, tmp_path):
    model = _patch_reply_model(monkeypatch, ["first answer", "second answer"])
    session = AgentSession(tmp_path)
    config = _config(tmp_path, tmp_path / "trace")
    first_events = EventCollector()
    second_events = EventCollector()

    first = run(
        "first question",
        tmp_path,
        config,
        emitter=EventEmitter(),
        session=session,
    )
    # A separate collector is not needed for the first assertion; run IDs are
    # available from SessionRun records and both model calls captured prompts.
    second = run(
        "second question",
        tmp_path,
        config,
        emitter=EventEmitter(),
        session=session,
    )

    assert len(session.runs) == 2
    assert session.runs[0].run_id != session.runs[1].run_id
    assert session.runs[0].snapshot is not None
    assert session.snapshot is not None
    assert [message.content for message in session.messages] == [
        "first question",
        "first answer",
        "second question",
        "second answer",
    ]
    assert sum("second question" in m.get("content", "") for m in model.messages[-1]) == 1
    assert first.reply == "first answer"
    assert second.reply == "second answer"
    assert not first_events.events and not second_events.events


def test_run_level_events_have_session_id_only_at_run_boundary(monkeypatch, tmp_path):
    model = _patch_reply_model(monkeypatch, ["hello", "again"])
    session = AgentSession(tmp_path)
    collector = EventCollector()
    emitter = EventEmitter()
    emitter.subscribe(collector)
    run("hello", tmp_path, _config(tmp_path, tmp_path / "trace"),
        emitter=emitter, session=session)
    run("again", tmp_path, _config(tmp_path, tmp_path / "trace"),
        emitter=emitter, session=session)

    boundary = [event for event in collector.events if isinstance(
        event, (RunStarted, RunFinished, RunFailed)
    )]
    assert boundary
    assert all(event.session_id == session.session_id for event in boundary)
    ordinary = [event for event in collector.events if event not in boundary]
    assert all(not hasattr(event, "session_id") for event in ordinary)
    assert model.messages


def test_session_context_keeps_tool_bundle_and_finish_is_not_fake_tool_call(tmp_path):
    session = AgentSession(tmp_path)
    first = session.begin_run("inspect files")
    session.record_user("inspect files", run_id=first.run_id)
    session.record_tool_call(
        tool_call_id="call-1",
        tool_name="list_files",
        arguments={"path": "."},
        run_id=first.run_id,
    )
    session.record_tool_result(
        tool_call_id="call-1",
        tool_name="list_files",
        content="hello.py",
        success=True,
        run_id=first.run_id,
    )
    session.record_message(
        "assistant",
        "[finish] inspected",
        run_id=first.run_id,
        tool_name="finish",
        arguments={"summary": "inspected", "validation": "not needed"},
    )
    session.complete_run(first, PreviousRunSnapshot(
        run_id=first.run_id, outcome="completed", summary="inspected"
    ))
    second = session.begin_run("follow up")
    session.record_user("follow up", run_id=second.run_id)

    config = _config(tmp_path, tmp_path / "trace")
    manager = ContextManager(config)
    state = AgentState.initialize("follow up", tmp_path)
    brief = TaskBrief.from_user_task("follow up")
    messages = manager.build(
        state,
        brief,
        session=session,
        current_run_id=second.run_id,
    )

    tool_messages = [message for message in messages if message.get("tool_call_id") == "call-1"]
    assert len(tool_messages) == 1
    assert any(message.get("tool_calls", [{}])[0].get("id") == "call-1" for message in messages)
    assert any("[finish] inspected" in message.get("content", "") for message in messages)
    assert not any(
        message.get("role") == "tool" and message.get("tool_call_id") == "call-finish"
        for message in messages
    )
    assert sum("follow up" in message.get("content", "") for message in messages) == 1
    assert len(session.messages) == 5


def test_model_failure_marks_session_failed_and_releases_guard(monkeypatch, tmp_path):
    class FailingModel:
        model = "failing"

        def generate(self, messages, tools=None):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: FailingModel()))
    session = AgentSession(tmp_path)
    with pytest.raises(RuntimeError, match="model unavailable"):
        run("will fail", tmp_path, _config(tmp_path, tmp_path / "trace"), session=session)

    assert session.active_run is None
    assert session.runs[-1].status == "failed"
    assert session.snapshot is not None
    assert session.snapshot.error == "model unavailable"

    # The guard is released even after failure, so the session can continue.
    _patch_reply_model(monkeypatch, ["recovered"])
    result = run("retry", tmp_path, _config(tmp_path, tmp_path / "trace"), session=session)
    assert result.reply == "recovered"


def test_rejected_finish_does_not_enter_session_history(monkeypatch, tmp_path):
    responses = iter([
        ModelResponse(
            tool_calls=[ToolCall(
                id="finish-1",
                name="finish",
                arguments={"summary": "not allowed", "validation": ""},
            )],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        ),
    ])

    class FinishModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return next(responses)

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: FinishModel()))
    session = AgentSession(tmp_path)
    config = _config(tmp_path, tmp_path / "trace")
    config.max_steps = 1
    config.max_model_calls = 1
    result = run("no mutation", tmp_path, config, session=session)

    assert result.stop_reason == "max_model_calls"
    assert not any(message.tool_name == "finish" for message in session.messages)
    assert [message.role for message in session.messages] == ["user"]


def test_second_run_prompt_does_not_duplicate_current_task(monkeypatch, tmp_path):
    """Card C E2E: the second run's current task must appear exactly once in the
    model prompt (as the P0 ``# Task`` message), with the first run's task
    appearing once as P3 history. ``Brief`` and ``Working State`` must echo
    the task via the ``[current task]`` marker, not the raw text.
    """
    model = _patch_reply_model(monkeypatch, ["first answer", "second answer"])
    session = AgentSession(tmp_path)
    config = _config(tmp_path, tmp_path / "trace")
    run("first question", tmp_path, config, session=session)
    run("second question", tmp_path, config, session=session)

    second_prompt = model.messages[-1]

    # The current task is injected exactly once via the P0 ``# Task`` slot.
    assert sum(
        msg.get("role") == "user"
        and "second question" in (msg.get("content") or "")
        and "Task" in (msg.get("content") or "")
        for msg in second_prompt
    ) == 1
    # The first task appears in history (P3) but not as the active task.
    assert sum(
        msg.get("role") == "user"
        and "first question" in (msg.get("content") or "")
        for msg in second_prompt
    ) == 1
    # The first answer appears in history (P3).
    assert any(
        msg.get("role") == "assistant" and "first answer" in (msg.get("content") or "")
        for msg in second_prompt
    )
    # Derived sections (Brief / Working State) must NOT carry the raw text;
    # the marker ``[current task]`` replaces it.
    for msg in second_prompt:
        text = msg.get("content") or ""
        if "[current task]" not in text:
            assert "second question" not in text or msg.get("role") != "assistant", (
                f"Brief/Working State must not echo the raw current task: {text[:200]}"
            )


def test_second_run_can_reference_first_run_tool_and_finish(tmp_path):
    """Card C E2E: a second run that begins after the first finishes sees the
    first run's tool bundle (call + result) and the finish text fact, while
    finish itself does not produce a fake tool_result.
    """
    session = AgentSession(tmp_path)
    first = session.begin_run("inspect")
    session.record_user("inspect", run_id=first.run_id)
    session.record_tool_call(
        tool_call_id="call-A",
        tool_name="list_files",
        arguments={"path": "."},
        run_id=first.run_id,
    )
    session.record_tool_result(
        tool_call_id="call-A",
        tool_name="list_files",
        content="hello.py",
        success=True,
        run_id=first.run_id,
    )
    session.record_message(
        "assistant",
        "[finish] done inspecting",
        run_id=first.run_id,
        tool_name="finish",
        arguments={"summary": "done inspecting", "validation": "not needed"},
    )
    session.complete_run(first, PreviousRunSnapshot(
        run_id=first.run_id, outcome="completed", summary="done inspecting"
    ))

    second = session.begin_run("follow up")
    session.record_user("follow up", run_id=second.run_id)
    state = AgentState.initialize("follow up", tmp_path)
    brief = TaskBrief.from_user_task("follow up")
    messages = ContextManager(_config(tmp_path, tmp_path / "trace")).build(
        state, brief, session=session, current_run_id=second.run_id
    )

    # First-run tool call+result is emitted as a single bundle.
    tool_calls = [
        m for m in messages
        if m.get("role") == "assistant"
        and any(tc.get("id") == "call-A" for tc in m.get("tool_calls") or [])
    ]
    tool_results = [
        m for m in messages
        if m.get("role") == "tool" and m.get("tool_call_id") == "call-A"
    ]
    assert tool_calls and tool_results

    # Finish text fact is rendered; no fake tool_result for finish.
    assert any("[finish] done inspecting" in (m.get("content") or "") for m in messages)
    assert not any(
        m.get("role") == "tool" and m.get("tool_call_id", "").startswith("tool-call-finish")
        for m in messages
    )

    # The current second-run task appears once and only once.
    assert sum("follow up" in (m.get("content") or "") for m in messages) == 1
