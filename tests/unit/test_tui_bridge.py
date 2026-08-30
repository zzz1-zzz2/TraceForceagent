"""Thread-bridge and worker tests for the TUI event bridge."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from textual.app import App
from textual.message import Message

from coding_agent.agent.brief import TaskMode
from coding_agent.agent.loop import AgentRunResult
from coding_agent.config import AgentConfig
from coding_agent.events import (
    AgentEvent,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
    ToolStarted,
)
from coding_agent.model.client import ModelClient
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall
from coding_agent.session import AgentSession
from coding_agent.tui.bridge import (
    AgentWorker,
    AgentWorkerError,
    AgentWorkerResult,
    TuiEventSink,
    UiAgentEvent,
)


class _MessageCollectingApp(App):
    """Capture every Message the worker posts."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[Message] = []

    def post_message(self, message: Message) -> bool:  # type: ignore[override]
        self.messages.append(message)
        return True


def _response(name: str, arguments: dict, call_id: str) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=1, output_tokens=1),
    )


def test_tui_event_sink_is_a_non_critical_best_oll_callable():
    app = _MessageCollectingApp()
    sink = TuiEventSink(app)
    assert sink.critical is False
    event = RunStarted(run_id="r", sequence=1)
    sink(event)
    assert len(app.messages) == 1
    assert isinstance(app.messages[0], UiAgentEvent)
    assert app.messages[0].event is event


def test_tui_event_sink_swallows_post_message_errors():
    class _Broken(App):
        def post_message(self, message: Message) -> bool:  # type: ignore[override]
            raise RuntimeError("queue full")

    sink = TuiEventSink(_Broken())
    sink(RunStarted(run_id="r", sequence=1))  # must not raise


def _stub_run_factory(
    *,
    responses: list[ModelResponse],
    run_id_holder: dict[str, str],
) -> Callable[..., AgentRunResult]:
    class FakeModel:
        model = "fake"

        def __init__(self, items: list[ModelResponse]) -> None:
            self._items = list(items)

        def generate(self, messages, tools=None):
            if not self._items:
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id="fallback",
                            name="finish",
                            arguments={"summary": "fallback", "validation": ""},
                        )
                    ],
                    finish_reason="tool_calls",
                    usage=TokenUsage(input_tokens=0, output_tokens=0),
                )
            return self._items.pop(0)

    def _factory(
        task: str,
        workspace: Path,
        config: AgentConfig,
        emitter,
        task_mode: TaskMode | str | None = None,
    ) -> AgentRunResult:
        from coding_agent.model.client import ModelClient as _Client

        def fake(cls, config):
            return FakeModel(list(responses))

        try:
            _Client.from_config = classmethod(fake)  # type: ignore[assignment]
            from coding_agent.agent.loop import run as agent_run

            return agent_run(
                task=task,
                workspace=workspace,
                config=config,
                emitter=emitter,
                task_mode=task_mode,
            )
        finally:
            _Client.from_config = classmethod(_Client.from_config.__func__)  # type: ignore[assignment]

    return _factory


def test_agent_worker_runs_loop_on_daemon_thread_and_posts_terminal_messages(
    monkeypatch, tmp_path: Path
):
    class FakeModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return _response(
                "list_files",
                {"path": ".", "max_depth": 1},
                "a1",
            )

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: FakeModel()))

    config = AgentConfig(
        workspace_root=tmp_path,
        trace_root=tmp_path / "trace",
        max_wall_time=30,
        max_steps=1,
        max_model_calls=1,
    )
    app = _MessageCollectingApp()

    started_threads: list[threading.Thread] = []

    def thread_factory(*args, **kwargs) -> threading.Thread:
        thread = threading.Thread(*args, **kwargs)
        started_threads.append(thread)
        return thread

    worker = AgentWorker(
        app,
        task="inspect",
        workspace=tmp_path,
        config=config,
        session=AgentSession(tmp_path),
        thread_factory=thread_factory,
    )
    thread = worker.start()
    thread.join(timeout=10)
    assert not worker.is_alive
    assert started_threads and started_threads[0] is thread
    assert thread.daemon is True

    event_messages = [m for m in app.messages if isinstance(m, UiAgentEvent)]
    terminal_results = [m for m in app.messages if isinstance(m, AgentWorkerResult)]
    terminal_errors = [m for m in app.messages if isinstance(m, AgentWorkerError)]
    assert not terminal_errors, terminal_errors
    assert terminal_results, "AgentWorkerResult was not posted"
    assert terminal_results[0].result.stop_reason == "max_steps"

    run_starts = [m for m in event_messages if isinstance(m.event, RunStarted)]
    assert run_starts, "RunStarted was never delivered to the sink"
    tool_starts = [m for m in event_messages if isinstance(m.event, ToolStarted)]
    assert tool_starts, "ToolStarted was never delivered to the sink"


def test_agent_worker_propagates_uncaught_exception(monkeypatch, tmp_path: Path):
    class FailingModel:
        model = "failing"

        def generate(self, messages, tools=None):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(ModelClient, "from_config", classmethod(lambda cls, config: FailingModel()))
    config = AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace")
    app = _MessageCollectingApp()
    worker = AgentWorker(
        app,
        task="boom",
        workspace=tmp_path,
        config=config,
        session=AgentSession(tmp_path),
    )
    thread = worker.start()
    thread.join(timeout=10)

    errors = [m for m in app.messages if isinstance(m, AgentWorkerError)]
    assert errors
    assert isinstance(errors[0].error, RuntimeError)


def test_agent_worker_cancel_is_idempotent(tmp_path: Path):
    config = AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace")
    app = _MessageCollectingApp()
    worker = AgentWorker(app, task="t", workspace=tmp_path, config=config)
    assert worker.cancel() is True
    assert worker.cancel() is False


def test_agent_worker_refuses_double_start(tmp_path: Path):
    config = AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace")
    app = _MessageCollectingApp()
    worker = AgentWorker(
        app,
        task="t",
        workspace=tmp_path,
        config=config,
        session=AgentSession(tmp_path),
    )
    worker.start()
    with pytest.raises(RuntimeError, match="already started"):
        worker.start()


def test_events_arrive_on_worker_thread_and_sink_queues_messages_for_app_thread(
    tmp_path: Path,
):
    config = AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace")
    app = _MessageCollectingApp()

    sink_threads: list[int] = []
    run_threads: list[int] = []

    def run_fn(*, emitter, **kwargs) -> AgentRunResult:
        run_threads.append(threading.get_ident())
        emitter.emit(RunFinished(
            run_id="r",
            final_state=RunStateSnapshot(status="COMPLETED", steps=1, total_tokens=0),
        ))
        return AgentRunResult(
            summary="done",
            validation="",
            stop_reason="finish",
            steps=1,
            total_tokens=0,
            duration=0.0,
            trajectory_path=None,
        )

    class _RecordingSink:
        critical = False

        def __init__(self, owner) -> None:
            self.owner = owner

        def __call__(self, event: AgentEvent) -> None:
            sink_threads.append(threading.get_ident())
            self.owner.post_message(UiAgentEvent(event))

    worker = AgentWorker(
        app,
        task="t",
        workspace=tmp_path,
        config=config,
        session=AgentSession(tmp_path),
        run_fn=run_fn,
    )

    main_thread = threading.get_ident()
    sink = _RecordingSink(app)
    worker.sink = sink  # type: ignore[assignment]
    thread = worker.start()
    thread.join(timeout=10)

    assert run_threads and run_threads[0] == thread.ident
    assert sink_threads == run_threads
    assert sink_threads[0] != main_thread
    assert len(app.messages) == 2


def test_bridge_does_not_block_event_emitter_when_post_message_returns_false(tmp_path: Path):
    class _ClosedApp(App):
        def post_message(self, message: Message) -> bool:  # type: ignore[override]
            return False

    sink = TuiEventSink(_ClosedApp())
    sink(RunStarted(run_id="r", sequence=1))  # must not raise


@pytest.mark.asyncio
async def test_messages_are_consumed_after_worker_finishes(tmp_path: Path):
    config = AgentConfig(workspace_root=tmp_path, trace_root=tmp_path / "trace")

    class _NoOpApp(App):
        def __init__(self) -> None:
            super().__init__()
            self.messages: list[Message] = []

        def post_message(self, message: Message) -> bool:  # type: ignore[override]
            self.messages.append(message)
            return True

    app = _NoOpApp()

    def quick_run(*args, **kwargs) -> AgentRunResult:
        return AgentRunResult(
            summary="x",
            validation="",
            stop_reason="finish",
            steps=1,
            total_tokens=1,
            duration=0.0,
            trajectory_path=None,
        )

    worker = AgentWorker(
        app,
        task="t",
        workspace=tmp_path,
        config=config,
        session=AgentSession(tmp_path),
        run_fn=quick_run,
    )
    thread = worker.start()
    thread.join(timeout=5)
    await asyncio.sleep(0)
    assert any(isinstance(m, AgentWorkerResult) for m in app.messages)
