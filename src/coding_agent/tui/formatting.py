"""Pure text formatting helpers for safe, bounded terminal rendering."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Final

PREVIEW_LINES: Final = 12
PREVIEW_CHARS: Final = 2_400
EXPANDED_LINES: Final = 200
EXPANDED_CHARS: Final = 32_000

_ANSI_ESCAPE: Final = re.compile(
    r"(?:\x1B\][^\x07]*(?:\x07|\x1B\\)|\x1B\[[0-?]*[ -/]*[@-~])"
)


def clean_text(value: object, *, limit: int | None = PREVIEW_CHARS) -> str:
    """Remove terminal controls and optionally bound text by character count."""
    text = _sanitize(value)
    return truncate_chars(text, limit) if limit is not None else text


def _sanitize(value: object) -> str:
    text = _ANSI_ESCAPE.sub("", str(value or ""))
    return "".join(
        char if char.isprintable() or char in "\n\t" else "�" for char in text
    )


def truncate_chars(text: str, limit: int) -> str:
    """Return text no longer than ``limit`` characters, including its marker."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return text[: limit - 1].rstrip() + "…"


def bound_lines(
    value: object,
    *,
    max_lines: int,
    max_chars: int | None = None,
    from_end: bool = False,
) -> str:
    """Sanitize and bound a text block by lines and then characters.

    The returned value never contains more than ``max_lines`` lines or more than
    ``max_chars`` characters. A marker occupies one line when line sampling is
    required, so the limits are absolute rather than approximate.
    """
    if max_lines <= 0:
        return ""
    text = _sanitize(value)
    lines = text.splitlines()
    if not lines:
        return ""

    if len(lines) > max_lines:
        keep = max_lines - 1
        marker = f"… ({len(lines) - keep} earlier lines)" if from_end else (
            f"… ({len(lines) - keep} later lines)"
        )
        if keep == 0:
            selected = ["…"]
        elif from_end:
            selected = [marker, *lines[-keep:]]
        else:
            selected = [*lines[:keep], marker]
        text = "\n".join(selected)

    if max_chars is not None:
        text = truncate_chars(text, max_chars)
    return text


def sample_text(
    value: object,
    *,
    lines: int = PREVIEW_LINES,
    chars: int = PREVIEW_CHARS,
    from_end: bool = False,
) -> str:
    """Return a bounded head or tail sample suitable for a collapsed card."""
    return bound_lines(value, max_lines=lines, max_chars=chars, from_end=from_end)


def preview(value: object, *, lines: int = PREVIEW_LINES) -> str:
    """Compatibility preview with the historical tail-and-marker behavior."""
    text = clean_text(value)
    chunks = text.splitlines()
    if len(chunks) > lines:
        return "\n".join(chunks[-lines:]) + f"\n… ({len(chunks) - lines} earlier lines)"
    return text


def compact_command(value: object) -> str:
    """Collapse command whitespace without exposing a raw argument mapping."""
    return " ".join(str(value or "").split())


def safe_path(value: object) -> str:
    """Format a user/tool supplied path as a short, safe display string."""
    path = str(value or ".")
    return clean_text(path, limit=160)


def remove_command_echo(output: object, command: str) -> str:
    """Remove shell-echo lines that duplicate a displayed command title."""
    text = _sanitize(output)
    if not command:
        return text
    echoes = {f"$ {command}", command}
    return "\n".join(line for line in text.splitlines() if line.strip() not in echoes)


def count_diff_lines(lines: Iterable[str]) -> tuple[int, int, int]:
    """Count added, removed, and context lines in unified diff text."""
    added = removed = context = 0
    for line in lines:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
        elif line.startswith(" "):
            context += 1
    return added, removed, context


def format_path_range(arguments: Mapping[str, object] | object, path: str) -> str:
    """Add a read-file line range when the tool arguments provide one."""
    if not isinstance(arguments, dict):
        return path
    start = arguments.get("start_line")
    end = arguments.get("end_line")
    if start is None and end is None:
        return path
    start_text = str(start if start is not None else 1)
    end_text = str(end if end is not None else start_text)
    return f"{path}:{start_text}–{end_text}"


__all__ = [
    "EXPANDED_CHARS",
    "EXPANDED_LINES",
    "PREVIEW_CHARS",
    "PREVIEW_LINES",
    "bound_lines",
    "clean_text",
    "compact_command",
    "count_diff_lines",
    "format_path_range",
    "preview",
    "remove_command_echo",
    "safe_path",
    "sample_text",
    "truncate_chars",
]
