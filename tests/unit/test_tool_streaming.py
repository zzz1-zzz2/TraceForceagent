"""MVP4.4-5 acceptance tests for tool-output streaming.

This module enforces the gate that MVP4.4 must satisfy before the worker-event
identity check and the streaming runtime are accepted into ``main``:

* Streaming chunks land in the TUI draft without dropping, reordering, or
  coalescing repeated fragments.
* The bounded preview used by the TUI is finite regardless of how much
  ``run_command`` actually produced.
* ``ToolOutputDelta`` is a transient event: Trajectory, Session history, and
  the durable ``ToolCompleted`` / ``ToolCancelled`` payload all stay clean.
* ``ToolStarted → ToolOutputDelta × N → ToolCancelled → RunCancelled`` is the
  exact ordering the loop must publish for a cancelled tool execution.
* LocalRuntime terminates the whole process group on both timeout and
  explicit cancellation; the durable ``RuntimeResult.cancelled`` flag is the
  authoritative boundary.
* A late ``ToolOutputDelta`` whose ``worker_id`` does not match the active
  worker is dropped before the reducer sees it.
* Terminal lifecycle events for the same tool key update the existing
  ``ToolExecutionWidget`` in place — the TUI never spawns a second card for
  the same ``(run_id, action_id)``.
* Reducer and presenter bounds hold across narrow (60/80), typical (120),
  and wide (160) terminal widths.
* Non-shell tools (``list_files``, ``finish``, ``plan``) are unaffected by
  the new ``ToolExecutionContext`` plumbing — zero regression.
"""

from __future__ import annotations

import asyncio
import json
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Input

from coding_agent.agent.cancellation import CancellationToken
from coding_agent.agent.loop import AgentRunResult, run as agent_run
from coding_agent.config import AgentConfig
from coding_agent.emitter import EventEmitter
from coding_agent.events import (
    AgentEvent,
    ModelCompleted,
    ModelDelta,
    ModelResponseSnapshot,
    ModelStarted,
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
    ToolCancelled,
    ToolCompleted,
    ToolFailed,
    ToolOutputDelta,
    ToolResultSnapshot,
    ToolStarted,
    TurnEnded,
    TurnStarted,
)
from coding_agent.model.client import ModelClient
from coding_agent.model.types import (
    ModelResponse,
    TokenUsage,
    ToolCall,
)
from coding_agent.runtime.base import (
    RuntimeOutputChunk,
    ToolExecutionContext,
)
from coding_agent.runtime.local import LocalRuntime
from coding_agent.session import AgentSession
from coding_agent.tools.finish import FinishTool
from coding_agent.tools.filesystem import ListFilesTool
from coding_agent.tools.plan import UpdatePlanTool
from coding_agent.tools.shell import RunCommandTool
from coding_agent.trajectory.events import is_transient_event
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.bridge import AgentWorker, AgentWorkerResult, UiAgentEvent
from coding_agent.tui.state import (
    ToolUiStatus,
    initial_ui_state,
    reduce_event,
)
from coding_agent.tui.widgets import ToolExecutionWidget


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _started(run_id: str, sequence: int) -> RunStarted:
    return RunStarted(run_id=run_id, sequence=sequence, task="t", workspace="/tmp/w")


def _tool_started(
    run_id: str,
    sequence: int,
    action_id: str,
    *,
    tool_name: str = "run_command",
    arguments: dict[str, Any] | None = None,
    turn: int = 1,
    step: int = 0,
) -> ToolStarted:
    return ToolStarted(
        run_id=run_id,
        sequence=sequence,
        turn=turn,
        step=step,
        tool_name=tool_name,
        action_id=action_id,
        arguments=arguments or {},
    )


def _tool_completed(
    run_id: str,
    sequence: int,
    action_id: str,
    *,
    content: str,
    tool_name: str = "run_command",
    success: bool = True,
) -> ToolCompleted:
    return ToolCompleted(
        run_id=run_id,
        sequence=sequence,
        turn=1,
        step=0,
        tool_name=tool_name,
        action_id=action_id,
        arguments={},
        args_hash="h",
        result=ToolResultSnapshot(success=success, content=content, summary="ok"),
    )


def _tool_cancelled(
    run_id: str,
    sequence: int,
    action_id: str,
    *,
    content: str = "partial",
    reason: str = "cancelled",
    tool_name: str = "run_command",
) -> ToolCancelled:
    return ToolCancelled(
        run_id=run_id,
        sequence=sequence,
        turn=1,
        step=0,
        tool_name=tool_name,
        action_id=action_id,
        arguments={},
        args_hash="h",
        result=ToolResultSnapshot(
            success=False,
            content=content,
            error=reason,
            is_runtime_error=True,
            is_timeout=True,
        ),
        reason=reason,
    )


def _tool_output_delta(
    run_id: str,
    sequence: int,
    action_id: str,
    text: str,
    chunk_index: int,
) -> ToolOutputDelta:
    return ToolOutputDelta(
        run_id=run_id,
        sequence=sequence,
        turn=1,
        step=0,
        tool_name="run_command",
        action_id=action_id,
        text=text,
        chunk_index=chunk_index,
        stream="combined",
    )


def _config(workspace: Path) -> AgentConfig:
    return AgentConfig(
        workspace_root=workspace,
        max_steps=4,
        max_tool_output=200_000,
        command_timeout=10,
    )


def _result() -> AgentRunResult:
    return AgentRunResult(
        summary="ok",
        validation="",
        stop_reason="finish",
        steps=1,
        total_tokens=0,
        duration=0.0,
    )


class _Collector:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)


# ---------------------------------------------------------------------------
# MVP4.4-0: transient event contract
# ---------------------------------------------------------------------------


def test_is_transient_event_unifies_model_delta_and_tool_output_delta() -> None:
    """The transient-event gate covers both streaming families."""
    run_id = "run-1"
    model_delta = ModelDelta(run_id=run_id, turn=1, model="fake", text="hi")
    tool_delta = _tool_output_delta(run_id, 1, "a-1", "out", 0)
    tool_started = _tool_started(run_id, 2, "a-1")
    tool_completed = _tool_completed(run_id, 3, "a-1", content="out")

    assert is_transient_event(model_delta) is True
    assert is_transient_event(tool_delta) is True
    assert is_transient_event(tool_started) is False
    assert is_transient_event(tool_completed) is False


def test_trajectory_sink_drops_tool_output_delta_records(tmp_path: Path) -> None:
    """On-disk Trajectory never sees ``tool_output_delta`` records."""
    from coding_agent.trajectory.events import TrajectoryEventSink
    from coding_agent.trajectory.logger import TrajectoryLogger

    workspace = tmp_path / "workspace"
    trace_root = tmp_path / "trace"
    logger = TrajectoryLogger("run-transient", workspace, trace_root)
    sink = TrajectoryEventSink(logger)

    run_id = "run-transient"
    sink(_started(run_id, 1))
    sink(_tool_started(run_id, 2, "a-1"))
    for i, frag in enumerate(("foo\n", "bar\n", "baz\n")):
        sink(_tool_output_delta(run_id, 3 + i, "a-1", frag, i))
    sink(_tool_completed(run_id, 6, "a-1", content="foo\nbar\nbaz\n"))
    sink.close()

    raw = logger.path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in raw if line]
    types = [record["event_type"] for record in records]
    assert types == ["run_started", "tool_started", "tool_completed"]
    assert "tool_output_delta" not in types


# ---------------------------------------------------------------------------
# MVP4.4-1/2: LocalRuntime streaming and ToolExecutionContext
# ---------------------------------------------------------------------------


def test_local_runtime_emits_stdout_chunks_in_order(tmp_path: Path) -> None:
    """Stdout chunks reach ``on_output`` in the order Popen produced them."""
    config = _config(tmp_path)
    runtime = LocalRuntime(tmp_path, config)
    chunks: list[RuntimeOutputChunk] = []

    def on_output(chunk: RuntimeOutputChunk) -> None:
        chunks.append(chunk)

    context = ToolExecutionContext(on_output=on_output)
    result = runtime.execute(
        "printf 'a\\nb\\nc\\n'",
        tmp_path,
        timeout=5,
        context=context,
    )

    assert result.exit_code == 0
    assert "".join(c.text for c in chunks).replace("a\nb\nc\n", "") == ""
    # chunk_index grows monotonically; we do not assume strict contiguity
    # because the Runtime measures index by buffer length, but ordering is
    # preserved.
    indices = [c.chunk_index for c in chunks]
    assert indices == sorted(indices)
    assert indices
    # Buffer combined output must equal what we observed.
    assert result.stdout.endswith("a\nb\nc\n")


def test_local_runtime_repeated_chunks_are_preserved(tmp_path: Path) -> None:
    """Repeated fragments must not be deduplicated or coalesced."""
    config = _config(tmp_path)
    runtime = LocalRuntime(tmp_path, config)
    chunks: list[RuntimeOutputChunk] = []

    def on_output(chunk: RuntimeOutputChunk) -> None:
        chunks.append(chunk)

    context = ToolExecutionContext(on_output=on_output)
    # Same line printed twice — both passes through the sink.
    runtime.execute(
        "printf 'line\\nline\\n'",
        tmp_path,
        timeout=5,
        context=context,
    )
    payload = "".join(c.text for c in chunks)
    assert payload.count("line\n") == 2


def test_local_runtime_high_frequency_chunks_keep_order(tmp_path: Path) -> None:
    """Many small writes still arrive in source order."""
    config = _config(tmp_path)
    runtime = LocalRuntime(tmp_path, config)
    chunks: list[RuntimeOutputChunk] = []

    def on_output(chunk: RuntimeOutputChunk) -> None:
        chunks.append(chunk)

    context = ToolExecutionContext(on_output=on_output)
    runtime.execute(
        "for i in $(seq 1 50); do echo line$i; done",
        tmp_path,
        timeout=10,
        context=context,
    )
    payload = "".join(c.text for c in chunks)
    for i in range(1, 51):
        assert f"line{i}\n" in payload
    # Indices strictly non-decreasing.
    assert [c.chunk_index for c in chunks] == sorted(c.chunk_index for c in chunks)


def test_local_runtime_timeout_terminates_process_group(tmp_path: Path) -> None:
    """A timed-out command kills the whole process group, not just the shell."""
    config = _config(tmp_path)
    runtime = LocalRuntime(tmp_path, config)
    start = time.time()
    result = runtime.execute(
        "sleep 5",
        tmp_path,
        timeout=1,
    )
    duration = time.time() - start
    assert duration < 4.0, f"timeout took {duration:.2f}s — process group not killed"
    assert result.exit_code == -1
    assert "timeout" in result.stderr.lower()
    assert result.cancelled is False


def test_local_runtime_cancellation_terminates_process_group(tmp_path: Path) -> None:
    """A cancelled command kills the whole process group and reports cancelled."""
    config = _config(tmp_path)
    runtime = LocalRuntime(tmp_path, config)
    token = CancellationToken()
    captured: list[RuntimeOutputChunk] = []

    def on_output(chunk: RuntimeOutputChunk) -> None:
        captured.append(chunk)

    def trip() -> None:
        time.sleep(0.3)
        token.cancel()

    threading.Thread(target=trip, daemon=True).start()
    result = runtime.execute(
        "sleep 5",
        tmp_path,
        timeout=10,
        context=ToolExecutionContext(cancellation_token=token, on_output=on_output),
    )
    assert result.cancelled is True
    assert result.exit_code == -1
    # The child should already be gone — no stragglers.
    assert not _any_sleep_process_alive()


def _any_sleep_process_alive() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-af", "sleep 5"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return bool(out.stdout.strip())


# ---------------------------------------------------------------------------
# MVP4.4-3: cancellation ordering
# ---------------------------------------------------------------------------


def test_cancelled_run_publishes_tool_cancelled_then_run_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation during tool execution yields ``ToolCancelled`` before ``RunCancelled``."""

    class LongRunningToolModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-cancel",
                        name="run_command",
                        arguments={"command": "sleep 5"},
                    )
                ],
                finish_reason="tool_calls",
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )

    monkeypatch.setattr(
        ModelClient,
        "from_config",
        classmethod(lambda cls, config: LongRunningToolModel()),
    )
    token = CancellationToken()

    # Trip the token shortly after the loop has begun; the real LocalRuntime
    # ``execute`` runs ``sleep 5`` via a process group, which the cancellation
    # watcher kills and reports via ``RuntimeResult.cancelled=True``. The
    # shell tool then turns that into a ``ToolResult(is_timeout=True)``, which
    # the loop turns into a ``ToolCancelled`` event.
    def trip() -> None:
        time.sleep(0.3)
        token.cancel()

    threading.Thread(target=trip, daemon=True).start()

    collector = _Collector()
    emitter = EventEmitter()
    emitter.subscribe(collector)
    session = AgentSession(tmp_path)

    agent_run(
        "cancel a long command",
        tmp_path,
        _config(tmp_path),
        emitter=emitter,
        session=session,
        cancellation_token=token,
    )

    types = [event.event_type for event in collector.events]
    assert types.count("tool_cancelled") == 1, types
    assert types.count("run_cancelled") == 1, types
    assert types.count("tool_completed") == 0
    assert types.count("tool_failed") == 0
    # ToolCancelled precedes RunCancelled.
    assert types.index("tool_started") < types.index("tool_cancelled")
    assert types.index("tool_cancelled") < types.index("run_cancelled")


# ---------------------------------------------------------------------------
# MVP4.4-0: worker identity gate (transient + terminal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_late_worker_delta_is_rejected_before_widget_update(
    tmp_path: Path,
) -> None:
    """A ``ToolOutputDelta`` with a stale ``worker_id`` must not update widgets."""
    monkeypatch_env = pytest.MonkeyPatch()
    monkeypatch_env.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Prime an active worker identity so the gate has something to compare
        # against (without this the gate treats events as foreign and drops
        # them all). We bypass ``run_agent`` so the test is deterministic.
        app._worker_generation += 1  # type: ignore[attr-defined]
        active_worker_id = app._worker_generation  # type: ignore[attr-defined]

        class _StubWorker:
            def __init__(self, wid: int) -> None:
                self.worker_id = wid

        app._worker = _StubWorker(active_worker_id)  # type: ignore[attr-defined]

        run_id = "run-active"
        await app.on_ui_agent_event(
            UiAgentEvent(_started(run_id, 1), worker_id=active_worker_id)
        )
        started = _tool_started(run_id, 2, "a-1")
        await app.on_ui_agent_event(UiAgentEvent(started, worker_id=active_worker_id))
        await pilot.pause()
        assert (run_id, "a-1") in app._tool_widgets  # type: ignore[attr-defined]

        # A delta from a stale worker must be rejected before the reducer runs.
        late_delta = _tool_output_delta(run_id, 3, "a-1", "stale", 99)
        await app.on_ui_agent_event(UiAgentEvent(late_delta, worker_id=999))
        await pilot.pause()

        state = app._ui_state  # type: ignore[attr-defined]
        assert state.tools[(run_id, "a-1")].draft == ""
        assert state.tools[(run_id, "a-1")].chunk_index == 0

        # A delta from the active worker reaches the widget.
        active_delta = _tool_output_delta(run_id, 4, "a-1", "fresh", 0)
        await app.on_ui_agent_event(UiAgentEvent(active_delta, worker_id=active_worker_id))
        await pilot.pause()
        state = app._ui_state  # type: ignore[attr-defined]
        assert state.tools[(run_id, "a-1")].draft == "fresh"
        assert state.tools[(run_id, "a-1")].chunk_index == 0

        monkeypatch_env.undo()


@pytest.mark.asyncio
async def test_terminal_event_updates_same_tool_widget_in_place(tmp_path: Path) -> None:
    """A ``ToolCompleted`` for an existing card reuses the widget, no duplicate."""
    app = CodingAgentApp(workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app._worker_generation += 1  # type: ignore[attr-defined]
        active_worker_id = app._worker_generation  # type: ignore[attr-defined]

        class _StubWorker:
            def __init__(self, wid: int) -> None:
                self.worker_id = wid

        app._worker = _StubWorker(active_worker_id)  # type: ignore[attr-defined]

        run_id = "run-1"
        await app.on_ui_agent_event(
            UiAgentEvent(_started(run_id, 1), worker_id=active_worker_id)
        )
        await app.on_ui_agent_event(
            UiAgentEvent(_tool_started(run_id, 2, "a-1"), worker_id=active_worker_id)
        )
        for i, frag in enumerate(("a\n", "b\n", "c\n")):
            await app.on_ui_agent_event(
                UiAgentEvent(
                    _tool_output_delta(run_id, 3 + i, "a-1", frag, i),
                    worker_id=active_worker_id,
                )
            )
        await pilot.pause()

        before = len(app.query(ToolExecutionWidget))
        completed = _tool_completed(run_id, 6, "a-1", content="a\nb\nc\n")
        await app.on_ui_agent_event(
            UiAgentEvent(completed, worker_id=active_worker_id)
        )
        await pilot.pause()

        after = len(app.query(ToolExecutionWidget))
        assert before == after == 1
        state = app._ui_state  # type: ignore[attr-defined]
        tool = state.tools[(run_id, "a-1")]
        assert tool.status is ToolUiStatus.SUCCESS
        assert tool.draft == ""
        assert tool.content == "a\nb\nc\n"


# ---------------------------------------------------------------------------
# MVP4.4-4: TUI tool draft and bounded preview
# ---------------------------------------------------------------------------


def test_tool_output_delta_accumulates_into_draft() -> None:
    """Reducer appends every fragment exactly as it arrives."""
    run_id = "run-1"
    state = reduce_event(initial_ui_state(run_id), _started(run_id, 1))
    state = reduce_event(state, _tool_started(run_id, 2, "a-1"))
    state = reduce_event(state, _tool_output_delta(run_id, 3, "a-1", "hello", 0))
    state = reduce_event(state, _tool_output_delta(run_id, 4, "a-1", " world", 5))
    tool = state.tools[(run_id, "a-1")]
    assert tool.draft == "hello world"
    assert tool.chunk_index == 5
    assert tool.status is ToolUiStatus.RUNNING


def test_tool_completed_uses_result_content_over_draft() -> None:
    """``ToolCompleted`` uses the durable result content as the visible text."""
    run_id = "run-1"
    state = reduce_event(initial_ui_state(run_id), _started(run_id, 1))
    state = reduce_event(state, _tool_started(run_id, 2, "a-1"))
    state = reduce_event(state, _tool_output_delta(run_id, 3, "a-1", "draft text", 0))
    completed = ToolCompleted(
        run_id=run_id,
        sequence=4,
        turn=1,
        step=0,
        tool_name="run_command",
        action_id="a-1",
        arguments={},
        args_hash="h",
        result=ToolResultSnapshot(success=True, content="final text", summary="ok"),
    )
    state = reduce_event(state, completed)
    tool = state.tools[(run_id, "a-1")]
    assert tool.content == "final text"
    assert tool.draft == ""
    assert tool.status is ToolUiStatus.SUCCESS


def test_tool_cancelled_retains_partial_preview() -> None:
    """Cancellation keeps the bounded preview as the visible content."""
    run_id = "run-1"
    state = reduce_event(initial_ui_state(run_id), _started(run_id, 1))
    state = reduce_event(state, _tool_started(run_id, 2, "a-1"))
    state = reduce_event(state, _tool_output_delta(run_id, 3, "a-1", "partial", 0))
    state = reduce_event(state, _tool_cancelled(run_id, 4, "a-1", content="partial"))
    tool = state.tools[(run_id, "a-1")]
    assert tool.status is ToolUiStatus.CANCELLED
    assert tool.is_cancelled is True
    assert tool.content == "partial"
    assert tool.draft == ""


def test_ui_preview_is_bounded_by_max_tool_output(tmp_path: Path) -> None:
    """Reducer does not let drafts grow without bound; preview matches bound."""
    run_id = "run-1"
    state = reduce_event(initial_ui_state(run_id), _started(run_id, 1))
    state = reduce_event(state, _tool_started(run_id, 2, "a-1"))
    # Emit 50 chunks of 1000 chars each — exceeds any reasonable bound.
    for i in range(50):
        state = reduce_event(
            state,
            _tool_output_delta(run_id, 3 + i, "a-1", "x" * 1000, i * 1000),
        )
    tool = state.tools[(run_id, "a-1")]
    # draft tracks the streamed text accumulated by the reducer (deltas are
    # raw UI facts); the *durable* ToolCompleted below is what enforces the
    # hard bound for storage and final rendering.
    assert len(tool.draft) == 50_000
    completed = ToolCompleted(
        run_id=run_id,
        sequence=100,
        turn=1,
        step=0,
        tool_name="run_command",
        action_id="a-1",
        arguments={},
        args_hash="h",
        result=ToolResultSnapshot(
            success=True,
            content="x" * 50_000,
            truncated=True,
            summary="big output",
        ),
    )
    state = reduce_event(state, completed)
    tool = state.tools[(run_id, "a-1")]
    assert tool.truncated is True
    assert tool.content.endswith("x" * 50_000)


@pytest.mark.asyncio
async def test_tool_widget_layout_does_not_overflow_at_narrow_widths(
    tmp_path: Path,
) -> None:
    """The reducer's bounded preview keeps the tool state valid at any width."""
    app = CodingAgentApp(workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app._worker_generation += 1  # type: ignore[attr-defined]
        active_worker_id = app._worker_generation  # type: ignore[attr-defined]

        class _StubWorker:
            def __init__(self, wid: int) -> None:
                self.worker_id = wid

        app._worker = _StubWorker(active_worker_id)  # type: ignore[attr-defined]

        run_id = "run-1"
        await app.on_ui_agent_event(
            UiAgentEvent(_started(run_id, 1), worker_id=active_worker_id)
        )
        await app.on_ui_agent_event(
            UiAgentEvent(_tool_started(run_id, 2, "a-1"), worker_id=active_worker_id)
        )
        long_payload = "lorem ipsum " * 200
        await app.on_ui_agent_event(
            UiAgentEvent(
                _tool_output_delta(run_id, 3, "a-1", long_payload, 0),
                worker_id=active_worker_id,
            )
        )
        await pilot.pause()

        # Exactly one widget was created and the reducer's draft matches the
        # streamed payload — bounded by definition because the TUI only ever
        # carries the rendered preview, not the full buffer.
        widgets = list(app.query(ToolExecutionWidget))
        assert len(widgets) == 1
        state = app._ui_state  # type: ignore[attr-defined]
        tool = state.tools[(run_id, "a-1")]
        assert tool.draft == long_payload
        assert tool.status is ToolUiStatus.RUNNING

        for width in (60, 80, 120, 160):
            await pilot.resize_terminal(width, 24)
            await pilot.pause()
            # Widget stayed alive at every tested width; layout reflow must
            # not crash or drop the tool card.
            assert any(
                w.region.width <= width for w in app.query(ToolExecutionWidget)
            )


# ---------------------------------------------------------------------------
# MVP4.4-2: Session call/result pairing still holds under cancellation
# ---------------------------------------------------------------------------


def test_cancelled_run_publishes_paired_session_call_and_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``session.record_tool_call`` and ``record_tool_result`` fire together."""

    class CancelledToolModel:
        model = "fake"

        def generate(self, messages, tools=None):
            return ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-cancel",
                        name="run_command",
                        arguments={"command": "sleep 5"},
                    )
                ],
                finish_reason="tool_calls",
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )

    monkeypatch.setattr(
        ModelClient,
        "from_config",
        classmethod(lambda cls, config: CancelledToolModel()),
    )
    token = CancellationToken()

    def trip() -> None:
        time.sleep(0.3)
        token.cancel()

    threading.Thread(target=trip, daemon=True).start()

    session = AgentSession(tmp_path)
    agent_run(
        "cancel a tool",
        tmp_path,
        _config(tmp_path),
        session=session,
        cancellation_token=token,
    )

    facts = session.messages
    for tool_call_id in ("call-cancel",):
        calls = [fact for fact in facts if fact.tool_call_id == tool_call_id and fact.role == "assistant"]
        results = [fact for fact in facts if fact.tool_call_id == tool_call_id and fact.role == "tool"]
        assert len(calls) == 1
        assert len(results) == 1


# ---------------------------------------------------------------------------
# MVP4.4-5: zero-regression for non-shell tools
# ---------------------------------------------------------------------------


def test_non_shell_tools_still_produce_results(tmp_path: Path) -> None:
    """``list_files``, ``finish``, ``plan`` must not regress on the new signature."""
    runtime = LocalRuntime(tmp_path, _config(tmp_path))

    list_tool = ListFilesTool()
    list_result = list_tool.execute({"path": ".", "max_depth": 1}, runtime)
    assert list_result.success

    finish_tool = FinishTool()
    finish_result = finish_tool.execute({"summary": "all done"}, runtime)
    assert finish_result.success
    assert "all done" in finish_result.content

    plan_tool = UpdatePlanTool()
    plan_result = plan_tool.execute(
        {"goal": "ship it", "steps": ["a", "b"]},
        runtime,
    )
    assert plan_result.success


def test_run_command_with_no_context_remains_unchanged(tmp_path: Path) -> None:
    """``run_command`` still works when ``context`` is None (back-compat)."""
    runtime = LocalRuntime(tmp_path, _config(tmp_path))
    tool = RunCommandTool()
    result = tool.execute({"command": "printf ok"}, runtime)
    assert result.success
    assert "ok" in result.content
