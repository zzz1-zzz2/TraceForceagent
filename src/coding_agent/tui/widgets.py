"""Componentized transcript and fixed status widgets for the TUI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click, Key
from textual.widget import Widget
from textual.widgets import Input, Markdown, Static

from coding_agent import __version__
from coding_agent.tui.formatting import clean_text, preview
from coding_agent.tui.presenters import present_tool
from coding_agent.tui.state import RunUiState, ToolUiState


# These compatibility helpers remain importable for existing callers while the
# tool-specific presentation contract lives in ``presenters.py``.
def _clean_text(value: object, *, limit: int = 2_400) -> str:
    """Make untrusted text safe and bounded for terminal rendering."""
    text = clean_text(value, limit=None)
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def _preview(value: object, *, lines: int = 12) -> str:
    """Return the historical bounded tail preview."""
    return preview(value, lines=lines)


def _path(arguments: Mapping[str, object]) -> str:
    return str(arguments.get("path") or arguments.get("cwd") or ".")


def tool_title(state: ToolUiState) -> str:
    """Return the presenter-generated compact tool title."""
    return present_tool(state).title


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
        self.add_class("assistant-message")

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

    can_focus = True

    def __init__(self, state: ToolUiState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state
        self.expanded = False
        self._can_expand = present_tool(state).can_expand
        self._header = Static(markup=False)
        self._summary = Static(markup=False)
        self._preview = Static(markup=False)
        self.add_class("tool-execution")

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._summary
        yield self._preview

    def on_mount(self) -> None:
        self.render_tool()

    def apply_state(self, state: ToolUiState) -> None:
        """Apply lifecycle state without changing local interaction state.

        The user's ``expanded`` flag survives across state updates so that
        an expanded card stays expanded as new tool results stream in.
        ``_can_expand`` is re-derived from the latest presentation so that
        ``toggle_expanded`` and the ``can_expand`` class toggle correctly
        reflect the new content.
        """
        self.state = state
        self._can_expand = present_tool(state).can_expand
        if self.is_mounted:
            self.render_tool()

    def set_expanded(self, expanded: bool) -> None:
        # Record the user's intent verbatim, even when ``can_expand`` is
        # False: rendering is a no-op in that case, but the flag survives
        # subsequent state updates that may again produce expandable
        # content.
        if self.expanded == expanded:
            return
        self.expanded = expanded
        self.render_tool()

    def toggle_expanded(self) -> None:
        if not self._can_expand:
            return
        self.set_expanded(not self.expanded)

    async def _on_click(self, event: Click) -> None:
        if event.button != 1:
            return
        # Treat the card surface and its direct sub-components as a single
        # click target so users can expand by clicking the header, summary,
        # or preview area in addition to the container itself.
        if event.widget is self or event.widget in (
            self._header,
            self._summary,
            self._preview,
        ):
            self.toggle_expanded()
            event.stop()
            return
        await super()._on_click(event)

    async def _on_key(self, event: Key) -> None:
        if event.key in {"enter", "space"} and self._can_expand:
            self.toggle_expanded()
            event.stop()
            return
        await super()._on_key(event)

    def render_tool(self) -> None:
        status = self.state.status.value
        icon = {"running": "●", "success": "✓", "error": "✗", "cancelled": "!"}.get(status, "•")
        self.set_class(status == "running", "running")
        for name in ("success", "error", "cancelled"):
            self.set_class(status == name, name)
        presentation = present_tool(self.state)
        self._can_expand = presentation.can_expand
        self.set_class(self.expanded, "expanded")
        self._header.update(f"{icon} {presentation.title}")
        self._summary.update(presentation.summary)
        shown = presentation.expanded_text if self.expanded else presentation.collapsed_text
        self._preview.update(shown)


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
        self._content = Static(markup=False)

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
        if state.modified_files:
            lines.append("modified: " + " · ".join(state.modified_files))
        lines.append(f"{state.step} steps · {state.total_tokens:,} tokens")
        if state.terminal_reason:
            lines.append(f"reason: {state.terminal_reason}")
        if state.terminal_error and state.terminal_error != state.terminal_reason:
            lines.append(f"error: {state.terminal_error}")
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
    "_clean_text",
    "_preview",
    "tool_title",
]
