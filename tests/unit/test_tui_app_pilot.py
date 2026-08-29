"""Headless Textual regression tests for the componentized TUI."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Input

from coding_agent.events import (
    AgentEvent,
    FinishAccepted,
    ModelCompleted,
    ModelResponseSnapshot,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
    ToolCompleted,
    ToolResultSnapshot,
    ToolStarted,
)
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.bridge import UiAgentEvent
from coding_agent.tui.state import ToolUiStatus
from coding_agent.tui.widgets import (
    AssistantMessageWidget,
    BrandBarWidget,
    FinalResultWidget,
    ToolExecutionWidget,
    TranscriptView,
    WelcomeWidget,
)


async def _post(app: CodingAgentApp, event: AgentEvent) -> None:
    await app.on_ui_agent_event(UiAgentEvent(event))


@pytest.mark.asyncio
async def test_app_mounts_fixed_chrome_and_welcome(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        assert app.query_one(BrandBarWidget)
        assert app.query_one(TranscriptView)
        assert app.query_one(WelcomeWidget)
        assert app.query_one("#run_status")
        assert app.query_one("#composer")
        assert app.query_one("#footer_meta")
        await pilot.pause()


@pytest.mark.asyncio
async def test_lifecycle_events_create_and_reuse_component_cards(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await _post(app, RunStarted(run_id="run-1", sequence=1, task="inspect"))
        await _post(
            app,
            ModelCompleted(
                run_id="run-1",
                sequence=2,
                turn=1,
                step=1,
                model="fake",
                response=ModelResponseSnapshot(content="hello"),
            ),
        )
        assert len(app.query(AssistantMessageWidget)) == 1
        await _post(
            app,
            ToolStarted(
                run_id="run-1",
                sequence=3,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                arguments={"command": "pytest -q"},
            ),
        )
        tool = app.query_one(ToolExecutionWidget)
        await _post(
            app,
            ToolCompleted(
                run_id="run-1",
                sequence=4,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                result=ToolResultSnapshot(success=False, content="failed", error="exit 1"),
            ),
        )
        assert len(app.query(ToolExecutionWidget)) == 1
        assert app.query_one(ToolExecutionWidget) is tool
        assert tool.state.status is ToolUiStatus.ERROR
        await pilot.pause()


@pytest.mark.asyncio
async def test_terminal_events_reuse_final_card_and_reenable_input(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await _post(app, RunStarted(run_id="run-1", sequence=1))
        app.query_one(Input).disabled = True
        await _post(
            app,
            FinishAccepted(
                run_id="run-1",
                sequence=2,
                turn=1,
                step=1,
                summary="done",
                final_state=RunStateSnapshot(status="COMPLETED", summary="done"),
            ),
        )
        final = app.query_one(FinalResultWidget)
        await _post(
            app,
            RunFinished(
                run_id="run-1",
                sequence=3,
                final_state=RunStateSnapshot(status="COMPLETED", summary="done", steps=1),
            ),
        )
        assert len(app.query(FinalResultWidget)) == 1
        assert app.query_one(FinalResultWidget) is final
        assert not app.query_one(Input).disabled
        await pilot.pause()


@pytest.mark.asyncio
async def test_run_failed_does_not_render_completed_state(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await _post(app, RunStarted(run_id="run-1", sequence=1))
        await _post(
            app,
            RunFailed(
                run_id="run-1",
                sequence=2,
                error_type="RuntimeError",
                error="boom",
                final_state=RunStateSnapshot(status="ERROR", reason="boom"),
            ),
        )
        assert len(app.query(FinalResultWidget)) == 1
        final = app.query_one(FinalResultWidget)
        assert "finished" not in final.classes
        assert "error" in final.classes
        await pilot.pause()
