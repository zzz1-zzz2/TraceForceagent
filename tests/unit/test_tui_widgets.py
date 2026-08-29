"""Unit tests for componentized TUI transcript widgets."""

from __future__ import annotations

from pathlib import Path

from coding_agent.tui.state import RunUiState, ToolUiState, ToolUiStatus
from coding_agent.tui.widgets import (
    AssistantMessageWidget,
    BrandBarWidget,
    FinalResultWidget,
    ToolExecutionWidget,
    _clean_text,
    _preview,
    tool_title,
)


def _tool(**overrides: object) -> ToolUiState:
    values: dict[str, object] = {
        "run_id": "run-1",
        "action_id": "action-1",
        "tool_name": "run_command",
        "arguments": {"command": "pytest -q"},
        "status": ToolUiStatus.RUNNING,
    }
    values.update(overrides)
    return ToolUiState(**values)  # type: ignore[arg-type]


def test_clean_text_removes_escape_sequences_and_control_characters() -> None:
    cleaned = _clean_text("hello\x1b[31m\x07world")
    assert "\x1b" not in cleaned
    assert "\x07" not in cleaned
    assert "hello" in cleaned
    assert "world" in cleaned


def test_clean_text_and_preview_are_bounded() -> None:
    assert _clean_text("x" * 20, limit=10) == "xxxxxxxxxx…"
    preview = _preview("\n".join(f"line-{i}" for i in range(15)), lines=3)
    assert preview.splitlines()[:3] == ["line-12", "line-13", "line-14"]
    assert "earlier lines" in preview


def test_tool_titles_use_compact_tool_specific_arguments() -> None:
    assert tool_title(_tool()) == "$ pytest -q"
    assert tool_title(_tool(tool_name="read_file", arguments={"path": "src/app.py"})) == "Read src/app.py"
    assert tool_title(_tool(tool_name="search_code", arguments={"query": "needle", "path": "."})) == 'Search "needle" in .'
    assert tool_title(_tool(tool_name="apply_patch", arguments={"path": "src/app.py", "patch": "secret"})) == "Modify src/app.py"


def test_tool_widget_keeps_one_instance_and_renders_states() -> None:
    widget = ToolExecutionWidget(_tool())
    assert widget.state.status is ToolUiStatus.RUNNING
    widget.apply_state(_tool(status=ToolUiStatus.SUCCESS, success=True, content="ok", summary="completed"))
    assert widget.state.status is ToolUiStatus.SUCCESS
    assert widget.state.content == "ok"
    widget.apply_state(_tool(status=ToolUiStatus.ERROR, success=False, error="exit 1"))
    assert widget.state.status is ToolUiStatus.ERROR
    assert widget.state.error == "exit 1"


def test_assistant_widget_retains_update_api_without_markup_processing() -> None:
    widget = AssistantMessageWidget("<not-a-tag> **hello**")
    assert widget.content == "<not-a-tag> **hello**"
    widget.append_delta(" text")
    assert widget.content == "<not-a-tag> **hello** text"


def test_final_result_widget_is_constructible_for_terminal_states() -> None:
    widget = FinalResultWidget()
    completed = RunUiState(
        run_id="run-1",
        finish_accepted=True,
        final_summary="done",
        final_validation="pytest -q",
        terminal=True,
        terminal_status="COMPLETED",
        step=2,
        total_tokens=10,
        modified_files=("app.py",),
    )
    widget.apply_state(completed)
    stopped = RunUiState(
        run_id="run-2",
        terminal=True,
        terminal_status="STOPPED",
        terminal_reason="max_steps",
    )
    widget.apply_state(stopped)
    failed = RunUiState(
        run_id="run-3",
        terminal=True,
        terminal_status="ERROR",
        terminal_reason="model failure",
    )
    widget.apply_state(failed)


def test_brand_widget_accepts_workspace_path() -> None:
    widget = BrandBarWidget(Path("/tmp/workspace"))
    assert widget.workspace == Path("/tmp/workspace")
