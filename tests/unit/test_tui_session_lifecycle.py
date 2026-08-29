"""MVP2 Card C — TUI session lifecycle contract tests.

These tests pin the cross-component contract between ``CodingAgentApp``,
``AgentWorker`` and ``AgentSession``. They were written first as failing
regressions; implementation follows in app.py / bridge.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from textual.widgets import Input

from coding_agent.agent.brief import TaskMode
from coding_agent.agent.loop import AgentRunResult
from coding_agent.config import AgentConfig
from coding_agent.events import (
    AssistantReplied,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
)
from coding_agent.session import AgentSession
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.bridge import AgentWorker, AgentWorkerResult, UiAgentEvent
from coding_agent.tui.widgets import NoticeWidget, WelcomeWidget

# ---------------------------------------------------------------------------
# Shared fakes and helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        workspace_root=tmp_path,
        trace_root=tmp_path / "trace",
        max_wall_time=30,
        max_steps=1,
        max_model_calls=1,
    )


def _patch_required_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"git", "rg"} else None,
    )


def _finish_result(reply: str | None = None) -> AgentRunResult:
    return AgentRunResult(
        summary=reply or "ok",
        validation="",
        stop_reason="assistant_reply" if reply else "finish",
        steps=0,
        total_tokens=0,
        duration=0.0,
        reply=reply,
    )


async def _post(app: CodingAgentApp, pilot, event) -> None:  # type: ignore[no-untyped-def]
    app.post_message(UiAgentEvent(event))
    await pilot.pause()


def _type_into_input(app: CodingAgentApp, value: str) -> None:
    """Push a value into the composer and dispatch ``Input.Submitted``."""
    input_widget = app.query_one("#input", Input)
    input_widget.value = value


# ---------------------------------------------------------------------------
# C.1.1 — App 持有唯一 Session
# ---------------------------------------------------------------------------


def test_app_init_creates_unique_session_for_workspace(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    assert isinstance(app._session, AgentSession)
    assert app._session.workspace == tmp_path.resolve()


def test_two_app_instances_have_independent_sessions(tmp_path: Path) -> None:
    a = CodingAgentApp(workspace=tmp_path)
    b = CodingAgentApp(workspace=tmp_path)
    assert a._session is not b._session
    assert a._session.session_id != b._session.session_id


# ---------------------------------------------------------------------------
# C.1.2 — Worker 借用 Session
# ---------------------------------------------------------------------------


def test_worker_borrows_session_without_mutating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Worker must receive the App's Session and never replace/clear it."""
    captured: dict[str, AgentSession | None] = {}

    def fake_run_fn(
        *,
        task: str,
        workspace: Path,
        config: AgentConfig,
        emitter,
        task_mode: TaskMode | str | None = None,
        session: AgentSession,
    ) -> AgentRunResult:
        captured["session"] = session
        return _finish_result()

    app_session = AgentSession(tmp_path)
    fake_app = CodingAgentApp(workspace=tmp_path)
    fake_app._session = app_session

    worker = AgentWorker(
        fake_app,
        task="t",
        workspace=tmp_path,
        config=_make_config(tmp_path),
        session=app_session,
        run_fn=fake_run_fn,
    )
    thread = worker.start()
    thread.join(timeout=5)

    assert captured["session"] is app_session


# ---------------------------------------------------------------------------
# C.1.3 — Worker 收尾前 Input 不可恢复
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_finished_alone_does_not_re_enable_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _post(app, pilot, RunStarted(run_id="r1", sequence=1))
        app.query_one(Input).disabled = True
        await _post(
            app,
            pilot,
            AssistantReplied(
                run_id="r1",
                sequence=2,
                turn=1,
                text="hi",
                final_state=RunStateSnapshot(
                    status="COMPLETED", reason="assistant_reply", summary="hi"
                ),
            ),
        )
        await _post(
            app,
            pilot,
            RunFinished(
                run_id="r1",
                sequence=3,
                final_state=RunStateSnapshot(
                    status="COMPLETED", reason="assistant_reply", summary="hi"
                ),
            ),
        )
        # RunFinished must NOT enable the Input. Only AgentWorkerResult
        # (worker thread fully returned) does.
        assert app.query_one(Input).disabled


@pytest.mark.asyncio
async def test_agent_worker_result_re_enables_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._worker = None  # sentinel: pretend worker is gone
        app.query_one(Input).disabled = True
        app.post_message(AgentWorkerResult(_finish_result("hi")))
        await pilot.pause()
        assert not app.query_one(Input).disabled
        assert app._worker is None


# ---------------------------------------------------------------------------
# C.1.4 — active-run guard 命中四种操作
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_run_guard_rejects_second_agent_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Simulate an active session run without spinning up a real worker.
        app._session.begin_run("active task")
        assert app._is_run_active()
        before_count = len(app.query(NoticeWidget))
        _type_into_input(app, "second task")
        app.post_message(Input.Submitted(input=app.query_one(Input), value="second task"))
        await pilot.pause()
        notices = app.query(NoticeWidget)
        assert len(notices) == before_count + 1
        assert "当前任务仍在运行" in str(notices[-1].content)


@pytest.mark.asyncio
async def test_active_run_guard_rejects_clear_workspace_chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._session.begin_run("active task")
        for command in ("/clear", "/workspace /tmp/elsewhere", "/chat hi", "plain task"):
            before_notices = len(app.query(NoticeWidget))
            _type_into_input(app, command)
            app.post_message(Input.Submitted(input=app.query_one(Input), value=command))
            await pilot.pause()
            notices = app.query(NoticeWidget)
            assert len(notices) == before_notices + 1, command
            assert "当前任务仍在运行" in str(notices[-1].content), command


@pytest.mark.asyncio
async def test_ctrl_l_clear_bypasses_active_run_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._session.begin_run("active")
        await pilot.press("ctrl+l")
        await pilot.pause()
        # Welcome widget re-appears; the session was NOT touched.
        assert app._session.is_active


# ---------------------------------------------------------------------------
# C.1.5 — /clear 保留 session_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_preserves_session_id_and_clears_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Seed history via the Session API. Use a snapshot to finish the run
        # cleanly so /clear is allowed.
        run = app._session.begin_run("first")
        app._session.record_user("first task", run_id=run.run_id)
        from coding_agent.session import PreviousRunSnapshot
        app._session.complete_run(
            run, PreviousRunSnapshot(run_id=run.run_id, summary="x")
        )
        assert app._session.messages  # seeded
        before_id = app._session.session_id
        _type_into_input(app, "/clear")
        app.post_message(Input.Submitted(input=app.query_one(Input), value="/clear"))
        await pilot.pause()
        assert app._session.session_id == before_id
        assert app._session.messages == ()
        assert app._session.runs == ()
        assert app._session.snapshot is None
        # Transcript reset to just the welcome widget.
        assert len(app.query(WelcomeWidget)) == 1


# ---------------------------------------------------------------------------
# C.1.6 — /workspace 更换 session_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_command_changes_session_id_and_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        new_path = tmp_path / "sub"
        before_id = app._session.session_id
        _type_into_input(app, f"/workspace {new_path}")
        app.post_message(
            Input.Submitted(input=app.query_one(Input), value=f"/workspace {new_path}")
        )
        await pilot.pause()
        assert app._session.session_id != before_id
        assert app._session.workspace == new_path.resolve()
        # Old session is no longer referenced.
        assert app._workspace == new_path.resolve()
        assert len(app.query(WelcomeWidget)) == 1


@pytest.mark.asyncio
async def test_workspace_command_rejected_while_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._session.begin_run("active")
        before_id = app._session.session_id
        before_workspace = app._session.workspace
        _type_into_input(app, "/workspace /tmp/other")
        app.post_message(
            Input.Submitted(input=app.query_one(Input), value="/workspace /tmp/other")
        )
        await pilot.pause()
        assert app._session.session_id == before_id
        assert app._session.workspace == before_workspace


# ---------------------------------------------------------------------------
# C.1.7 — preflight failure 不进 Session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_failure_does_not_touch_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    # No credentials — preflight with require_credentials=True fails.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRACEFORCE_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        before_id = app._session.session_id
        await app.run_agent("will be rejected by preflight")
        await pilot.pause()
        assert app._session.session_id == before_id
        assert app._session.runs == ()
        assert app._session.messages == ()
        assert app._session.is_active is False
        assert app._worker is None
        # Worker must not have started.
        assert app.query_one(Input).disabled is False
        error_notices = [n for n in app.query(NoticeWidget) if n.level == "error"]
        assert any("preflight failed" in str(n.content) for n in error_notices)


# ---------------------------------------------------------------------------
# C.1 (extra) — /chat 走 Agent 而不是旁路 chat
# ---------------------------------------------------------------------------


def test_app_no_longer_exposes_run_chat_or_chat_history(tmp_path: Path) -> None:
    """C.4: the chat bypass was deleted. /chat is a routing alias for Agent."""
    app = CodingAgentApp(workspace=tmp_path)
    assert not hasattr(app, "run_chat")
    assert not hasattr(app, "_chat_history")
    assert not hasattr(app, "_chat_system")


# ---------------------------------------------------------------------------
# C.5 — 统一 Worker 收尾
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_worker_resets_worker_and_enables_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_required_tools(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        sentinel = object()
        app._worker = sentinel  # type: ignore[assignment]
        app.query_one(Input).disabled = True
        app._complete_worker()
        assert app._worker is None
        assert app.query_one(Input).disabled is False
