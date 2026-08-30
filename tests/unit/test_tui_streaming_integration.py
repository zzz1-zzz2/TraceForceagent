"""Deterministic worker-to-Textual streaming integration tests."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from textual.widgets import Input

from coding_agent.agent.loop import AgentRunResult
from coding_agent.events import (
    ModelCompleted,
    ModelDelta,
    ModelResponseSnapshot,
    ModelStarted,
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
    TurnEnded,
    TurnStarted,
)
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.bridge import AgentWorker, AgentWorkerResult
from coding_agent.tui.widgets import AssistantMessageWidget, FinalResultWidget


@pytest.mark.asyncio
async def test_worker_stream_reaches_one_stable_tui_card_before_teardown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real worker messages update the TUI before completion re-enables input."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    released = threading.Event()
    emitted = threading.Event()
    workers: list[AgentWorker] = []

    def stream_run(*, emitter, **kwargs) -> AgentRunResult:
        run_id = "worker-run"
        emitter.emit(RunStarted(run_id=run_id, task="stream"))
        emitter.emit(TurnStarted(run_id=run_id, turn=1))
        emitter.emit(ModelStarted(run_id=run_id, turn=1, model="fake"))
        emitter.emit(ModelDelta(run_id=run_id, turn=1, model="fake", text="hello"))
        emitter.emit(ModelDelta(run_id=run_id, turn=1, model="fake", text=" world"))
        emitter.emit(ModelCompleted(
            run_id=run_id,
            turn=1,
            model="fake",
            response=ModelResponseSnapshot(content="hello world"),
        ))
        emitter.emit(TurnEnded(run_id=run_id, turn=1, status="finished"))
        emitter.emit(RunFinished(
            run_id=run_id,
            final_state=RunStateSnapshot(
                status="COMPLETED",
                reason="finish",
                summary="streamed",
            ),
        ))
        emitted.set()
        assert released.wait(5), "test did not release the worker"
        return AgentRunResult(
            summary="streamed",
            validation="",
            stop_reason="finish",
            steps=0,
            total_tokens=0,
            duration=0.0,
        )

    def worker_factory(owner, **kwargs):
        worker = AgentWorker(owner, run_fn=stream_run, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("coding_agent.tui.app.AgentWorker", worker_factory)
    app = CodingAgentApp(workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.run_agent("stream a response")
        assert emitted.wait(5)
        await pilot.pause()

        assert len(workers) == 1
        assert app._worker is workers[0]  # type: ignore[attr-defined]
        assert app.query_one(Input).disabled
        assert app._ui_state.assistant_messages == ("hello world",)
        assert app._ui_state.assistant_drafts == {}
        assert len(app.query(AssistantMessageWidget)) == 1
        assert app.query_one(AssistantMessageWidget).content == "hello world"
        assert len(app.query(FinalResultWidget)) == 1

        released.set()
        for _ in range(5):
            await pilot.pause(delay=0.05)
        assert app._worker is None  # type: ignore[attr-defined]
        assert not app.query_one(Input).disabled


@pytest.mark.asyncio
async def test_worker_failure_flushes_pending_stream_without_model_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Worker errors flush the draft and do not append another assistant card."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    emitted = threading.Event()

    def failing_run(*, emitter, **kwargs) -> AgentRunResult:
        emitter.emit(RunStarted(run_id="failed-run", task="stream"))
        emitter.emit(ModelStarted(run_id="failed-run", turn=1, model="fake"))
        emitter.emit(ModelDelta(run_id="failed-run", turn=1, model="fake", text="partial"))
        emitter.emit(RunFailed(
            run_id="failed-run",
            error_type="RuntimeError",
            error="worker exploded",
            final_state=RunStateSnapshot(status="ERROR", reason="worker exploded"),
        ))
        emitted.set()
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(
        "coding_agent.tui.app.AgentWorker",
        lambda owner, **kwargs: AgentWorker(owner, run_fn=failing_run, **kwargs),
    )
    app = CodingAgentApp(workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.run_agent("fail after streaming")
        assert emitted.wait(5)
        for _ in range(10):
            await pilot.pause(delay=0.05)
            if app._worker is None:  # type: ignore[attr-defined]
                break
        assert app._worker is None  # type: ignore[attr-defined]
        assert not app.query_one(Input).disabled
        assert len(app.query(AssistantMessageWidget)) == 1
        assert app.query_one(AssistantMessageWidget).content == "partial"
        assert len(app.query(FinalResultWidget)) == 1
        assert "error" in str(app.query_one("#run_status").render())


@pytest.mark.asyncio
async def test_worker_cancellation_flushes_pending_stream_without_error_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cancelled worker output remains visible without a false error notice."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    emitted = threading.Event()

    def cancelled_run(*, emitter, cancellation_token, **kwargs) -> AgentRunResult:
        emitter.emit(RunStarted(run_id="cancel-run", task="stream"))
        emitter.emit(ModelStarted(run_id="cancel-run", turn=1, model="fake"))
        emitter.emit(ModelDelta(run_id="cancel-run", turn=1, model="fake", text="partial"))
        emitted.set()
        cancellation_token.cancel()
        emitter.emit(RunCancelled(
            run_id="cancel-run",
            final_state=RunStateSnapshot(status="CANCELLED", reason="cancelled"),
        ))
        return _result()

    monkeypatch.setattr(
        "coding_agent.tui.app.AgentWorker",
        lambda owner, **kwargs: AgentWorker(owner, run_fn=cancelled_run, **kwargs),
    )
    app = CodingAgentApp(workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.run_agent("cancel after streaming")
        assert emitted.wait(5)
        for _ in range(10):
            await pilot.pause(delay=0.05)
            if app._worker is None:  # type: ignore[attr-defined]
                break
        assert app._worker is None  # type: ignore[attr-defined]
        assert not app.query_one(Input).disabled
        assert app.query_one(AssistantMessageWidget).content == "partial"
        assert len(app.query(FinalResultWidget)) == 1
        assert "cancelled" in str(app.query_one("#run_status").render())
        assert "error" not in str(app.query_one("#run_status").render())


@pytest.mark.asyncio
async def test_late_worker_completion_cannot_reenable_new_worker_input(
    tmp_path: Path,
) -> None:
    """A completion from an old worker is ignored while a newer worker is active."""
    app = CodingAgentApp(workspace=tmp_path)

    class WorkerMarker:
        def __init__(self, worker_id: int) -> None:
            self.worker_id = worker_id

    async with app.run_test() as pilot:
        await pilot.pause()
        app._worker = WorkerMarker(2)  # type: ignore[assignment]
        app.query_one(Input).disabled = True
        app.post_message(AgentWorkerResult(_result(), worker_id=1))
        await pilot.pause()
        assert app._worker.worker_id == 2  # type: ignore[union-attr]
        assert app.query_one(Input).disabled

        app.post_message(AgentWorkerResult(_result(), worker_id=2))
        await pilot.pause()
        assert app._worker is None  # type: ignore[attr-defined]
        assert not app.query_one(Input).disabled


def _result() -> AgentRunResult:
    return AgentRunResult(
        summary="done",
        validation="",
        stop_reason="finish",
        steps=0,
        total_tokens=0,
        duration=0.0,
    )
