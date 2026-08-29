"""Headless Textual regression tests for the componentized TUI."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Input

from coding_agent.agent.loop import AgentRunResult
from coding_agent.events import (
    AgentEvent,
    AssistantReplied,
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
from coding_agent.tui.bridge import AgentWorkerResult, UiAgentEvent
from coding_agent.tui.state import ToolUiStatus
from coding_agent.tui.widgets import (
    AssistantMessageWidget,
    BrandBarWidget,
    FinalResultWidget,
    ToolExecutionWidget,
    TranscriptView,
    WelcomeWidget,
)


async def _post(app: CodingAgentApp, pilot, event: AgentEvent) -> None:
    app.post_message(UiAgentEvent(event))
    await pilot.pause()


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
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1, task="inspect"))
        await _post(
            app,
            pilot,
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
            pilot,
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
            pilot,
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
async def test_assistant_reply_renders_and_reenables_input(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
        app.query_one(Input).disabled = True
        await _post(app, pilot, AssistantReplied(
            run_id="run-1",
            sequence=2,
            turn=1,
            text="你好，世界",
            final_state=RunStateSnapshot(
                status="COMPLETED", reason="assistant_reply", summary="你好，世界"
            ),
        ))
        await _post(app, pilot, RunFinished(
            run_id="run-1",
            sequence=3,
            final_state=RunStateSnapshot(
                status="COMPLETED", reason="assistant_reply", summary="你好，世界"
            ),
        ))
        assert len(app.query(AssistantMessageWidget)) == 1
        # Card C: RunFinished alone must NOT enable the Input. The worker
        # thread still has ``session.complete_run`` to finish. Only the
        # ``AgentWorkerResult`` message that the worker posts after
        # ``agent_run`` returns may re-enable the composer.
        assert app.query_one(Input).disabled
        app.post_message(AgentWorkerResult(AgentRunResult(
            summary="你好，世界",
            validation="",
            stop_reason="assistant_reply",
            steps=0,
            total_tokens=0,
            duration=0.0,
            reply="你好，世界",
        )))
        await pilot.pause()
        assert not app.query_one(Input).disabled


    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
        app.query_one(Input).disabled = True
        await _post(
            app,
            pilot,
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
            pilot,
            RunFinished(
                run_id="run-1",
                sequence=3,
                final_state=RunStateSnapshot(status="COMPLETED", summary="done", steps=1),
            ),
        )
        assert len(app.query(FinalResultWidget)) == 1
        assert app.query_one(FinalResultWidget) is final
        # Card C: same contract — RunFinished keeps the Input disabled until
        # the worker thread returns.
        assert app.query_one(Input).disabled
        app.post_message(AgentWorkerResult(AgentRunResult(
            summary="done",
            validation="",
            stop_reason="finish",
            steps=1,
            total_tokens=0,
            duration=0.0,
        )))
        await pilot.pause()
        assert not app.query_one(Input).disabled
        await pilot.pause()


@pytest.mark.asyncio
async def test_run_failed_refreshes_running_tool_to_error(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
        await _post(
            app,
            pilot,
            ToolStarted(
                run_id="run-1",
                sequence=2,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                arguments={"command": "sleep 1"},
            ),
        )
        tool = app.query_one(ToolExecutionWidget)
        assert tool.state.status is ToolUiStatus.RUNNING
        await _post(
            app,
            pilot,
            RunFailed(
                run_id="run-1",
                sequence=3,
                error_type="RuntimeError",
                error="boom",
                final_state=RunStateSnapshot(status="ERROR", reason="boom"),
            ),
        )
        assert app.query_one(ToolExecutionWidget) is tool
        assert tool.state.status is ToolUiStatus.ERROR
        await pilot.pause()


@pytest.mark.asyncio
async def test_run_failed_does_not_render_completed_state(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
        await _post(
            app,
            pilot,
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


@pytest.mark.asyncio
async def test_tool_keyboard_mouse_and_global_toggle_preserve_local_state(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
        await _post(
            app,
            pilot,
            ToolStarted(
                run_id="run-1",
                sequence=2,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                arguments={"command": "printf output"},
            ),
        )
        # Send enough output that ``can_expand`` is True — otherwise the
        # Enter/Space/click affordances are a deliberate no-op.
        long_output = "\n".join(f"line-{i}" for i in range(40))
        await _post(
            app,
            pilot,
            ToolCompleted(
                run_id="run-1",
                sequence=3,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                result=ToolResultSnapshot(success=True, content=long_output),
            ),
        )
        tool = app.query_one(ToolExecutionWidget)
        tool.focus()
        await pilot.press("enter")
        assert tool.expanded
        await pilot.press("space")
        assert not tool.expanded
        await pilot.click(tool, offset=(1, 0))
        assert tool.expanded
        tool.focus()
        await pilot.press("ctrl+o")
        assert not tool.expanded
        await pilot.press("ctrl+o")
        assert tool.expanded
        app.query_one(Input).focus()
        await pilot.press("a", "space")
        assert app.query_one(Input).value == "a "
        await pilot.press("escape")
        assert app.focused is app.query_one(Input)


@pytest.mark.asyncio
async def test_expanded_tool_stays_expanded_when_terminal_event_arrives(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
        await _post(
            app,
            pilot,
            ToolStarted(
                run_id="run-1",
                sequence=2,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                arguments={"command": "printf output"},
            ),
        )
        tool = app.query_one(ToolExecutionWidget)
        tool.set_expanded(True)
        await _post(
            app,
            pilot,
            ToolCompleted(
                run_id="run-1",
                sequence=3,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                result=ToolResultSnapshot(success=True, content="done"),
            ),
        )
        assert app.query_one(ToolExecutionWidget) is tool
        assert tool.expanded
        assert tool.state.status is ToolUiStatus.SUCCESS


# --- P2-1C.3.1 Tool UI hardening ---------------------------------------------


def _long_command_result(*, lines: int = 40) -> str:
    return "\n".join(f"line-{i}" for i in range(lines)) + "\nfinal-error-line"


async def _seed_expandable_tool(
    app: CodingAgentApp, pilot, *, action_id: str = "a1"
) -> ToolExecutionWidget:
    await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
    await _post(
        app,
        pilot,
        ToolStarted(
            run_id="run-1",
            sequence=2,
            turn=1,
            step=1,
            tool_name="run_command",
            action_id=action_id,
            arguments={"command": "printf output"},
        ),
    )
    await _post(
        app,
        pilot,
        ToolCompleted(
            run_id="run-1",
            sequence=3,
            turn=1,
            step=1,
            tool_name="run_command",
            action_id=action_id,
            result=ToolResultSnapshot(success=True, content=_long_command_result()),
        ),
    )
    return app.query_one(ToolExecutionWidget)


@pytest.mark.asyncio
async def test_sub_component_clicks_toggle_tool_expansion(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        tool = await _seed_expandable_tool(app, pilot)
        # Header click toggles.
        await pilot.click(tool._header)
        assert tool.expanded
        # Summary click toggles back.
        await pilot.click(tool._summary)
        assert not tool.expanded
        # Preview click toggles.
        await pilot.click(tool._preview)
        assert tool.expanded


@pytest.mark.asyncio
async def test_tool_collapse_is_noop_when_cannot_expand(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
        await _post(
            app,
            pilot,
            ToolStarted(
                run_id="run-1",
                sequence=2,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                arguments={"command": "echo hi"},
            ),
        )
        await _post(
            app,
            pilot,
            ToolCompleted(
                run_id="run-1",
                sequence=3,
                turn=1,
                step=1,
                tool_name="run_command",
                action_id="a1",
                result=ToolResultSnapshot(success=True, content="hi"),
            ),
        )
        tool = app.query_one(ToolExecutionWidget)
        # Content is short — can_expand is False; toggles must be a no-op.
        assert not tool._can_expand
        tool.toggle_expanded()
        assert tool.expanded is False
        await pilot.click(tool._header)
        assert tool.expanded is False
        await pilot.click(tool._preview)
        assert tool.expanded is False


@pytest.mark.asyncio
async def test_escape_does_not_raise_when_input_is_disabled(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await _post(app, pilot, RunStarted(run_id="run-1", sequence=1))
        input_widget = app.query_one(Input)
        input_widget.disabled = True  # simulate an in-flight worker
        await pilot.press("escape")
        # No exception was raised and focus remains where it was.
        assert input_widget.disabled
        # Re-enable and verify the focus path is exercised again.
        input_widget.disabled = False
        await pilot.press("escape")
        assert app.focused is input_widget


@pytest.mark.parametrize("width", [60, 80, 120])
@pytest.mark.asyncio
async def test_tui_does_not_overflow_at_narrow_widths(
    tmp_path: Path, width: int
) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    async with app.run_test(size=(width, 30)) as pilot:
        tool = await _seed_expandable_tool(app, pilot)
        # Expanded and collapsed renderings must both fit the width and never
        # report a horizontal scrollbar in the fixed layout.
        for expanded in (False, True):
            tool.set_expanded(expanded)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            assert transcript.allow_horizontal_scroll is False or (
                not transcript.allow_horizontal_scroll
            ), "transcript must not allow horizontal scrolling"
            # The rendered widget's content region must be at most ``width``.
            region = tool.content_region
            assert region.width <= width
