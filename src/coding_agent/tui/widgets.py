"""Componentized transcript and fixed status widgets for the TUI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, Markdown, Static

from coding_agent import __version__
from coding_agent.tui.state import RunUiState, ToolUiState, ToolUiStatus

_PREVIEW_LINES: Final = 12
_PREVIEW_CHARS: Final = 2400


def _clean_text(value: object, *, limit: int = _PREVIEW_CHARS) -> str:
    """Make untrusted tool output safe and bounded for terminal rendering."""
    text = str(value or "").replace("\x1b", "")
    text = "".join(char if char.isprintable() or char in "\n\t" else "�" for char in text)
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def _preview(value: object, *, lines: int = _PREVIEW_LINES) -> str:
    text = _clean_text(value)
    chunks = text.splitlines()
    if len(chunks) > lines:
        return "\n".join(chunks[-lines:]) + f"\n… ({len(chunks) - lines} earlier lines)"
    return text


def _path(arguments: Mapping[str, object]) -> str:
    return str(arguments.get("path") or arguments.get("cwd") or ".")


def tool_title(state: ToolUiState) -> str:
    """Return a compact, tool-specific title without dumping raw JSON."""
    arguments = state.arguments
    if state.tool_name == "run_command":
        command = " ".join(str(arguments.get("command", "")).split())
        return "$ " + _clean_text(command, limit=160)
    if state.tool_name == "read_file":
        return f"Read {_clean_text(_path(arguments), limit=160)}"
    if state.tool_name == "list_files":
        return f"List {_clean_text(_path(arguments), limit=160)}"
    if state.tool_name == "search_code":
        query = _clean_text(arguments.get("query", ""), limit=80)
        return f'Search "{query}" in {_clean_text(_path(arguments), limit=120)}'
    if state.tool_name in {"apply_patch", "patch"}:
        return f"Modify {_clean_text(_path(arguments), limit=160)}"
    if state.tool_name == "git_diff":
        return "Inspect changes"
    if state.tool_name == "update_plan":
        return "Update plan"
    return _clean_text(state.tool_name or "Tool", limit=160)


class BrandBarWidget(Static):
    """Persistent product identity bar."""

    def __init__(self, workspace: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.workspace = workspace

    def on_mount(self) -> None:
        self.render_brand()

    def set_workspace(self, workspace: Path) -> None:
        self.workspace = workspace
        self.render_brand()

    def render_brand(self) -> None:
        self.update(f"TraceForce · v{__version__} · {_clean_text(self.workspace)}")


class TranscriptView(VerticalScroll):
    """Scrollable transcript host; business state remains in the app/reducer."""

    async def append_entry(self, widget: Widget) -> None:
        await self.mount(widget)
        self.scroll_end(animate=False, force=True)

    async def clear_entries(self) -> None:
        await self.remove_children()

    def follow_output(self) -> None:
        self.scroll_end(animate=False, force=True)


class WelcomeWidget(Static):
    """Compact initial prompt that yields to transcript entries."""

    def __init__(self, workspace: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.workspace = workspace

    def on_mount(self) -> None:
        self.render_welcome()

    def set_workspace(self, workspace: Path) -> None:
        self.workspace = workspace
        self.render_welcome()

    def render_welcome(self) -> None:
        self.update(
            "TraceForce\n"
            f"workspace  {_clean_text(self.workspace)}\n"
            "Enter a task to inspect, change, and validate this workspace."
        )


class UserMessageWidget(Static):
    """One user task or explicit chat message."""

    def __init__(self, content: str, *, chat: bool = False, **kwargs: Any) -> None:
        super().__init__(id=None, **kwargs)
        self.content = content
        self.chat = chat

    def on_mount(self) -> None:
        self.update(f"> {_clean_text(self.content, limit=1200)}")
        self.add_class("chat" if self.chat else "task")


class AssistantMessageWidget(Vertical):
    """Markdown assistant response, ready for future delta updates."""

    def __init__(self, content: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.content = content
        self.markdown = Markdown(content)

    def compose(self) -> ComposeResult:
        yield self.markdown

    def set_content(self, content: str) -> None:
        self.content = content
        if self.markdown.is_mounted:
            self.markdown.update(content)

    def append_delta(self, delta: str) -> None:
        self.set_content(self.content + delta)


class ToolExecutionWidget(Vertical):
    """One stable tool card updated by ``run_id + action_id``."""

    def __init__(self, state: ToolUiState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state
        self.add_class("tool-execution")
        self._header = Static()
        self._summary = Static()
        self._preview = Static()

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._summary
        yield self._preview

    def on_mount(self) -> None:
        self.render_tool()

    def apply_state(self, state: ToolUiState) -> None:
        self.state = state
        if self.is_mounted:
            self.render_tool()

    def set_expanded(self, expanded: bool) -> None:
        self.state = replace(self.state, expanded=expanded)
        self.render_tool()

    def render_tool(self) -> None:
        status = self.state.status.value
        icon = {"running": "●", "success": "✓", "error": "✗", "cancelled": "!"}.get(status, "•")
        self.set_class(status == "running", "running")
        for name in ("success", "error", "cancelled"):
            self.set_class(status == name, name)
        self._header.update(f"{icon} {tool_title(self.state)}")
        if self.state.status is ToolUiStatus.RUNNING:
            summary = "running"
        elif self.state.is_runtime_error:
            summary = self.state.error or "runtime error"
        elif self.state.is_validation_failure:
            summary = self.state.summary or "validation failed"
        else:
            summary = self.state.summary or ("completed" if self.state.success else "failed")
        self._summary.update(_clean_text(summary, limit=320))
        content = self.state.error if self.state.status is ToolUiStatus.ERROR and self.state.error else self.state.content
        shown = content if self.state.expanded else _preview(content)
        self._preview.update(_clean_text(shown) or "(no output)")


class ValidationWidget(Static):
    """Compact validation result."""

    def __init__(self, *, passed: bool | None, summary: str, command: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.passed = passed
        self.summary = summary
        self.command = command

    def on_mount(self) -> None:
        self.render_validation()

    def render_validation(self) -> None:
        label = "passed" if self.passed else "failed"
        self.add_class("passed" if self.passed else "failed")
        self.update(f"{'✓' if self.passed else '✗'} validation {label} · {_clean_text(self.summary or self.command, limit=360)}")


class NoticeWidget(Static):
    """Bounded system, feedback, or error notice."""

    def __init__(self, content: str, *, level: str = "system", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.content = content
        self.level = level

    def on_mount(self) -> None:
        self.add_class(self.level)
        self.update(_clean_text(self.content, limit=800))


class FinalResultWidget(Vertical):
    """Single final card updated by FinishAccepted and RunFinished/RunFailed."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._content = Static()

    def compose(self) -> ComposeResult:
        yield self._content

    def apply_state(self, state: RunUiState) -> None:
        status = state.terminal_status or ("COMPLETED" if state.finish_accepted else "")
        icon = "✓" if status == "COMPLETED" else "!" if status == "STOPPED" else "✗"
        self.set_class(status == "COMPLETED", "finished")
        self.set_class(status == "STOPPED", "stopped")
        self.set_class(status not in {"", "COMPLETED", "STOPPED"}, "error")
        lines = [f"{icon} {status.lower() or 'finishing'}"]
        if state.final_summary:
            lines.append(state.final_summary)
        if state.final_validation:
            lines.append(f"validation: {state.final_validation}")
        if state.validation_skipped_reason:
            lines.append(f"validation skipped: {state.validation_skipped_reason}")
        if state.final_notes:
            lines.append(f"notes: {state.final_notes}")
            lines.append("modified: " + " · ".join(state.modified_files))
        lines.append(f"{state.step} steps · {state.total_tokens:,} tokens")
        if state.terminal_reason:
            lines.append(f"reason: {state.terminal_reason}")
        self._content.update(_clean_text("\n".join(lines), limit=1800))


class RunStatusWidget(Static):
    """Fixed status indicator driven by reducer state."""

    def apply_state(self, state: RunUiState) -> None:
        phase = state.phase
        if state.terminal:
            icon = "✓" if phase == "finished" else "!" if phase == "stopped" else "✗"
            text = f"{icon} {phase} · {state.step} steps · {state.total_tokens:,} tokens"
        elif phase == "idle":
            text = "ready"
        else:
            icon = "✻" if phase in {"thinking", "working", "validation"} else "•"
            text = f"{icon} {phase} · turn {state.turn} · step {state.step}"
            if state.model:
                text += f" · {state.model}"
        self.update(_clean_text(text, limit=240))


class ComposerBarWidget(Horizontal):
    """Fixed input area, kept visible while the worker runs."""

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Describe a coding task or use /chat <message>",
            id="input",
        )


class FooterMetaWidget(Static):
    """Fixed workspace and shortcut metadata."""

    def __init__(self, workspace: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.workspace = workspace

    def on_mount(self) -> None:
        self.render_footer()

    def set_workspace(self, workspace: Path) -> None:
        self.workspace = workspace
        self.render_footer()

    def apply_state(self, state: RunUiState) -> None:
        self.update(
            f"{_clean_text(self.workspace)} · {state.model or 'model'} · "
            f"{state.total_tokens:,} tokens · Ctrl+L clear · Ctrl+C quit"
        )

    def render_footer(self) -> None:
        self.update(f"{_clean_text(self.workspace)} · Ctrl+L clear · Ctrl+C quit")


__all__ = [
    "AssistantMessageWidget",
    "BrandBarWidget",
    "ComposerBarWidget",
    "FinalResultWidget",
    "FooterMetaWidget",
    "NoticeWidget",
    "RunStatusWidget",
    "ToolExecutionWidget",
    "TranscriptView",
    "UserMessageWidget",
    "ValidationWidget",
    "WelcomeWidget",
    "tool_title",
]
