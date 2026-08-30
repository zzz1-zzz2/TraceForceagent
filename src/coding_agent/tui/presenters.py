"""Pure presenters for bounded, tool-specific TUI content."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from coding_agent.tui.formatting import (
    EXPANDED_CHARS,
    EXPANDED_LINES,
    PREVIEW_CHARS,
    PREVIEW_LINES,
    bound_lines,
    clean_text,
    compact_command,
    count_diff_lines,
    format_path_range,
    remove_command_echo,
    safe_path,
    sample_text,
)
from coding_agent.tui.state import ToolUiState, ToolUiStatus


@dataclass(frozen=True, slots=True)
class ToolPresentation:
    """All data needed by a tool card, independent of Textual widgets."""

    title: str
    summary: str
    collapsed_text: str
    expanded_text: str
    can_expand: bool
    hidden_lines: int
    preview_kind: str


def present_tool(state: ToolUiState) -> ToolPresentation:
    """Present a tool snapshot using its built-in pure presenter."""
    presenter = _PRESENTERS.get(state.tool_name, _present_generic)
    return presenter(state)


def _present_generic(state: ToolUiState) -> ToolPresentation:
    content = _content(state)
    return _make_presentation(
        title=clean_text(state.tool_name or "Tool", limit=160),
        summary=_summary(state, "completed" if state.success else "failed"),
        content=content,
        collapsed=sample_text(content, lines=PREVIEW_LINES, chars=PREVIEW_CHARS),
        preview_kind="text",
    )


def _present_run_command(state: ToolUiState) -> ToolPresentation:
    arguments = state.arguments
    command = compact_command(arguments.get("command", ""))
    content = remove_command_echo(_content(state), command)
    # Shell commands almost always finish with the most informative line
    # (exit status, exception traceback, "FAILED" tail, etc.). Tail-sampling
    # without a guard can drop it, so we pin the very last line into the
    # collapsed preview.
    collapsed = sample_text(
        content,
        lines=PREVIEW_LINES,
        chars=PREVIEW_CHARS,
        from_end=True,
        keep_last=True,
    )
    return _make_presentation(
        title="$ " + clean_text(command, limit=160),
        summary=_summary(state, "running"),
        content=content,
        collapsed=collapsed,
        preview_kind="terminal",
    )


def _present_read_file(state: ToolUiState) -> ToolPresentation:
    arguments = state.arguments
    path = safe_path(arguments.get("path", "."))
    title_path = format_path_range(arguments, path)
    content = _content(state)
    return _make_presentation(
        title="Read " + clean_text(title_path, limit=180),
        summary=_summary(state, f"read {title_path}"),
        content=content,
        collapsed=sample_text(content, lines=PREVIEW_LINES, chars=PREVIEW_CHARS),
        preview_kind="file",
    )


def _present_list_files(state: ToolUiState) -> ToolPresentation:
    path = safe_path(state.arguments.get("path", "."))
    content = _content(state)
    return _make_presentation(
        title="List " + path,
        summary=_summary(state, _list_summary(content)),
        content=content,
        collapsed=sample_text(content, lines=PREVIEW_LINES, chars=PREVIEW_CHARS),
        preview_kind="listing",
    )


def _present_search_code(state: ToolUiState) -> ToolPresentation:
    query = clean_text(state.arguments.get("query", ""), limit=80)
    path = safe_path(state.arguments.get("path", "."))
    content = _content(state)
    return _make_presentation(
        title=f'Search "{query}" in {path}',
        summary=_summary(state, _search_summary(content)),
        content=content,
        collapsed=sample_text(content, lines=PREVIEW_LINES, chars=PREVIEW_CHARS),
        preview_kind="search",
    )


def _present_patch(state: ToolUiState) -> ToolPresentation:
    arguments = state.arguments
    mode = str(arguments.get("mode", "modify")).lower()
    path = safe_path(arguments.get("path", "."))
    labels = {"create": "Create", "delete": "Delete", "modify": "Modify"}
    action = labels.get(mode, "Modify")
    content = _content(state)
    added, removed, _ = count_diff_lines(content.splitlines())
    stat = f"+{added} -{removed}" if added or removed else _patch_stat(state, mode)
    return _make_presentation(
        title=f"{action} {path}",
        summary=_summary(state, f"{stat} · {path}"),
        content=content,
        collapsed=sample_text(content, lines=PREVIEW_LINES, chars=PREVIEW_CHARS),
        preview_kind="diff",
    )


def _present_git_diff(state: ToolUiState) -> ToolPresentation:
    content = _content(state)
    added, removed, context = count_diff_lines(content.splitlines())
    files = _diff_file_count(content)
    fallback = f"{files} files · +{added} -{removed} · {context} context"
    return _make_presentation(
        title="Inspect changes",
        summary=_summary(state, fallback),
        content=content,
        collapsed=sample_text(content, lines=PREVIEW_LINES, chars=PREVIEW_CHARS),
        preview_kind="diff",
    )


def _present_plan(state: ToolUiState) -> ToolPresentation:
    items = state.arguments.get("items", [])
    counts = {"completed": 0, "in_progress": 0, "pending": 0}
    if isinstance(items, (list, tuple)):
        for item in items:
            if isinstance(item, Mapping):
                status = str(item.get("status", "pending"))
                if status in counts:
                    counts[status] += 1
    summary = _summary(
        state,
        f"{counts['completed']} done · {counts['in_progress']} active · "
        f"{counts['pending']} pending",
    )
    content = _content(state)
    if not content and isinstance(items, (list, tuple)):
        content = "\n".join(
            f"{_plan_icon(item)} {clean_text(item.get('content', ''), limit=240)}"
            for item in items
            if isinstance(item, Mapping)
        )
    return _make_presentation(
        title="Update plan",
        summary=summary,
        content=content,
        collapsed=sample_text(content, lines=PREVIEW_LINES, chars=PREVIEW_CHARS),
        preview_kind="checklist",
    )


def _make_presentation(
    *,
    title: str,
    summary: str,
    content: str,
    collapsed: str,
    preview_kind: str,
) -> ToolPresentation:
    expanded = bound_lines(
        content,
        max_lines=EXPANDED_LINES,
        max_chars=EXPANDED_CHARS,
    )
    collapsed_text = bound_lines(
        collapsed,
        max_lines=PREVIEW_LINES,
        max_chars=PREVIEW_CHARS,
    )
    hidden_lines = max(0, len(content.splitlines()) - len(collapsed_text.splitlines()))
    return ToolPresentation(
        title=clean_text(title, limit=200),
        summary=clean_text(summary, limit=360),
        collapsed_text=collapsed_text or "(no output)",
        expanded_text=expanded or "(no output)",
        can_expand=expanded != collapsed_text,
        hidden_lines=hidden_lines,
        preview_kind=preview_kind,
    )


def _content(state: ToolUiState) -> str:
    if state.status is ToolUiStatus.RUNNING and state.draft:
        return state.draft
    if state.status is ToolUiStatus.ERROR and state.error:
        return state.error
    return state.content


def _summary(state: ToolUiState, fallback: str) -> str:
    if state.status is ToolUiStatus.RUNNING:
        return "running"
    if state.is_runtime_error:
        return state.error or "runtime error"
    if state.is_validation_failure:
        return state.summary or "validation failed"
    return state.summary or fallback


def _list_summary(content: str) -> str:
    if not content:
        return "0 entries"
    return f"{len(content.splitlines())} entries"


def _search_summary(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].lower().startswith(("found ", "no matches")):
        return lines[0]
    return f"{len(lines)} matches"


def _patch_stat(state: ToolUiState, mode: str) -> str:
    if mode == "create":
        return "new file"
    if mode == "delete":
        return "deleted file"
    return "changed file"


def _diff_file_count(content: str) -> int:
    paths = set()
    for line in content.splitlines():
        if line.startswith("+++ b/"):
            paths.add(line[6:])
        elif line.startswith("--- a/"):
            paths.add(line[6:])
    return len(paths)


def _plan_icon(item: Mapping[str, object]) -> str:
    return {"pending": "☐", "in_progress": "▶", "completed": "☑"}.get(
        str(item.get("status", "pending")), "?"
    )


_PRESENTERS: dict[str, Callable[[ToolUiState], ToolPresentation]] = {
    "run_command": _present_run_command,
    "read_file": _present_read_file,
    "list_files": _present_list_files,
    "search_code": _present_search_code,
    "apply_patch": _present_patch,
    "patch": _present_patch,
    "git_diff": _present_git_diff,
    "update_plan": _present_plan,
}

__all__ = ["ToolPresentation", "present_tool"]
