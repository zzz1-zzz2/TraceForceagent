"""Unit tests for componentized TUI transcript widgets."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import cast

from coding_agent.tui.formatting import bound_lines, format_path_range, sample_text
from coding_agent.tui.presenters import present_tool
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
    cleaned = _clean_text("hello\x1b[31mred\x1b[0m\x1b]0;title\x07\x07world")
    assert "\x1b" not in cleaned
    assert "[31m" not in cleaned
    assert "[0m" not in cleaned
    assert "hello" in cleaned
    assert "red" in cleaned
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


def test_final_result_shows_modified_files_without_notes() -> None:
    widget = FinalResultWidget()
    state = RunUiState(
        run_id="run-1",
        terminal=True,
        terminal_status="COMPLETED",
        final_summary="done",
        modified_files=("a.py", "b.py"),
    )
    widget.apply_state(state)
    content = cast(str, widget._content._Static__content)  # type: ignore[attr-defined]
    assert content == "✓ completed\ndone\nmodified: a.py · b.py\n0 steps · 0 tokens"


def test_tool_presenters_cover_built_in_tools() -> None:
    cases = [
        (_tool(tool_name="read_file", arguments={"path": "app.py", "start_line": 2, "end_line": 8}, content="# app.py (lines 2-8 of 20)\n\n   2\tmain"), "Read app.py:2–8", "file"),
        (_tool(tool_name="list_files", arguments={"path": "src"}, content="one.py\ntwo.py"), "List src", "listing"),
        (_tool(tool_name="search_code", arguments={"query": "needle", "path": "src"}, content="Found 1 matches for 'needle':\nsrc/app.py:1:needle"), 'Search "needle" in src', "search"),
        (_tool(tool_name="apply_patch", arguments={"path": "new.py", "mode": "create"}, content="Created new.py\n(12 bytes)"), "Create new.py", "diff"),
        (_tool(tool_name="apply_patch", arguments={"path": "old.py", "mode": "delete"}, content="Deleted old.py"), "Delete old.py", "diff"),
        (_tool(tool_name="git_diff", content="--- a/app.py\n+++ b/app.py\n@@\n-old\n+new"), "Inspect changes", "diff"),
        (_tool(tool_name="update_plan", arguments={"items": [{"status": "completed", "content": "done"}, {"status": "in_progress", "content": "now"}, {"status": "pending", "content": "later"}]}, content="Plan updated:"), "Update plan", "checklist"),
        (_tool(tool_name="custom_tool", content="raw result"), "custom_tool", "text"),
    ]
    for state, title, kind in cases:
        presentation = present_tool(state)
        assert presentation.title == title
        assert presentation.preview_kind == kind
        assert presentation.collapsed_text
        assert presentation.expanded_text


def test_tool_presenters_bound_both_collapsed_and_expanded_output() -> None:
    content = "\n".join(f"line-{index}" for index in range(500))
    presentation = present_tool(_tool(content=content))
    assert len(presentation.collapsed_text) <= 2_400
    assert len(presentation.expanded_text) <= 32_000
    assert len(presentation.collapsed_text.splitlines()) <= 12
    assert len(presentation.expanded_text.splitlines()) <= 200


def test_run_command_presenter_uses_tail_and_removes_echo() -> None:
    state = _tool(content="$ pytest -q\n" + "\n".join(f"line-{i}" for i in range(20)))
    presentation = present_tool(state)
    assert "$ pytest -q" not in presentation.collapsed_text
    assert "line-19" in presentation.collapsed_text
    assert "line-0" not in presentation.collapsed_text


def test_patch_and_diff_presenters_do_not_expose_raw_patch_arguments() -> None:
    state = _tool(
        tool_name="apply_patch",
        arguments={
            "path": "app.py",
            "mode": "modify",
            "old_string": "PRIVATE_OLD_CONTENT",
            "new_string": "PRIVATE_NEW_CONTENT",
        },
        content="@@\n-old\n+new",
        status=ToolUiStatus.SUCCESS,
        success=True,
    )
    presentation = present_tool(state)
    assert "+1 -1" in presentation.summary
    assert "PRIVATE_OLD_CONTENT" not in presentation.expanded_text
    assert "PRIVATE_NEW_CONTENT" not in presentation.expanded_text


def test_tool_widget_expansion_is_local_and_survives_state_updates() -> None:
    widget = ToolExecutionWidget(_tool(content="first\nsecond"))
    widget.set_expanded(True)
    widget.apply_state(_tool(status=ToolUiStatus.SUCCESS, success=True, content="updated"))
    assert widget.expanded is True
    assert not hasattr(widget.state, "expanded")


def test_brand_widget_accepts_workspace_path() -> None:
    widget = BrandBarWidget(Path("/tmp/workspace"))
    assert widget.workspace == Path("/tmp/workspace")


# --- P2-1C.3.1 Tool UI hardening ---------------------------------------------


def test_format_path_range_accepts_mapping_proxy() -> None:
    """Reducer-produced immutable arguments must keep their line range."""
    args = MappingProxyType({"path": "src/app.py", "start_line": 3, "end_line": 9})
    assert format_path_range(args, "src/app.py") == "src/app.py:3–9"


def test_format_path_range_returns_path_when_not_mapping() -> None:
    assert format_path_range("not a mapping", "src/app.py") == "src/app.py"
    assert format_path_range(None, "src/app.py") == "src/app.py"


def test_bound_lines_keep_last_pins_tail_error_line() -> None:
    """Tail sampling must include the very last source line so the user
    always sees the final error / exit reason from a shell command."""
    text = "\n".join(f"line-{i}" for i in range(40)) + "\nTraceback (most recent call last)"
    bounded = bound_lines(
        text, max_lines=5, max_chars=None, from_end=True, keep_last=True
    )
    lines = bounded.splitlines()
    assert lines[-1] == "Traceback (most recent call last)"
    assert len(lines) <= 5
    # Earlier truncation marker still appears.
    assert any("earlier lines" in line for line in lines)


def test_sample_text_keep_last_does_not_drop_when_short_input() -> None:
    short = "ok\nfail"
    assert sample_text(short, lines=12, from_end=True, keep_last=True).endswith("fail")


def test_run_command_presenter_keeps_last_error_line_in_collapsed_preview() -> None:
    state = _tool(
        content="\n".join(f"line-{i}" for i in range(40)) + "\nTraceback (most recent call last)"
    )
    presentation = present_tool(state)
    assert "Traceback (most recent call last)" in presentation.collapsed_text
    # The very first lines are dropped by tail sampling, but the last line
    # is preserved regardless of the cap.
    assert "line-0" not in presentation.collapsed_text


def test_widget_toggle_is_noop_when_cannot_expand() -> None:
    widget = ToolExecutionWidget(_tool(content="short"))
    assert not present_tool(widget.state).can_expand
    widget.toggle_expanded()
    assert widget.expanded is False
    widget.set_expanded(True)
    # Setting expanded to True is allowed (records intent), but toggle stays
    # gated on ``can_expand`` so click/keyboard presses remain a no-op when
    # there is nothing more to show.
    widget.toggle_expanded()
    assert widget.expanded is True


def test_widget_apply_state_updates_can_expand_but_keeps_expanded_flag() -> None:
    long_content = "\n".join(f"line-{i}" for i in range(60))
    widget = ToolExecutionWidget(_tool(content=long_content))
    widget.set_expanded(True)
    assert widget.expanded is True
    # Shrink the content so can_expand becomes False — the user's expanded
    # intent is preserved across state updates; only ``toggle_expanded``
    # gates on the new ``can_expand``.
    widget.apply_state(_tool(content="tiny", status=ToolUiStatus.SUCCESS, success=True))
    assert widget.expanded is True
