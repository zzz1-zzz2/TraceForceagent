"""User-level TraceForce configuration loaded from TOML.

The user config lives at ``~/.config/traceforce/config.toml`` on Linux.
It is **never** a credential source: API keys, tokens, and any other
secrets MUST come from explicit environment variables or ``--env-file``,
not from this file. The :data:`NON_SENSITIVE_KEYS` allow-list is the only
contract between the file and :func:`coding_agent.config.load_config`;
anything outside the allow-list is silently dropped.

The loader never raises to its caller. A malformed TOML yields
``values={}`` and ``source="parse-error"``; preflight surfaces that as a
warning so the CLI/TUI can continue with defaults.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final


class UserConfigSource(StrEnum):
    """How the user-level TOML config was sourced."""

    FILE = "file"
    DEFAULT_MISSING = "default-missing"
    PARSE_ERROR = "parse-error"


# Allow-list of safe, non-sensitive AgentConfig fields that may be set
# from the user TOML. Anything outside this set is dropped before the
# values are merged into ``load_config``. Credential-shaped keys MUST
# never be added here, even if a future card introduces a new provider.
NON_SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        # provider selection (id only — key/url still come from resolver)
        "active_provider",
        # model / endpoint
        "active_model",
        "active_base_url",
        # model behaviour
        "temperature",
        # agent limits
        "max_steps",
        "max_model_calls",
        "max_wall_time",
        "command_timeout",
        "max_tool_output",
        "context_budget",
        "recent_turns",
        # logging
        "log_level",
        "log_json",
        # mode switches
        "enable_failure_refresh",
        # paths (still non-sensitive; trace_root never holds credentials)
        "trace_root",
        "workspace_root",
    }
)


# Forbidden key shapes. We drop any TOML key that matches one of these
# patterns even if a caller mistakenly added it to the allow-list.
_FORBIDDEN_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i).*api[_-]?key$"),
    re.compile(r"(?i).*token$"),
    re.compile(r"(?i).*secret$"),
    re.compile(r"(?i).*password$"),
    re.compile(r"(?i)^permission"),
    re.compile(r"(?i)^sandbox"),
)


def default_user_config_path() -> Path:
    """Return the default user config path under ``$XDG_CONFIG_HOME`` or
    ``~/.config`` when ``XDG_CONFIG_HOME`` is unset."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / "traceforce" / "config.toml"
    return Path.home() / ".config" / "traceforce" / "config.toml"


@dataclass(frozen=True, slots=True)
class UserConfig:
    """Result of attempting to load the user TOML config.

    ``values`` is already filtered against :data:`NON_SENSITIVE_KEYS` and
    the forbidden patterns, so callers can splat it straight into the
    AgentConfig field set without re-checking keys.
    """

    path: Path
    exists: bool
    source: UserConfigSource
    values: Mapping[str, Any]
    parse_error: str = ""


def _is_forbidden(key: str) -> bool:
    return any(pattern.match(key) for pattern in _FORBIDDEN_PATTERNS)


def _filter_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the allow-list and the forbidden-pattern filter."""
    filtered: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if key not in NON_SENSITIVE_KEYS:
            continue
        if _is_forbidden(key):
            continue
        filtered[key] = value
    return filtered


def load_user_config(path: Path | None = None) -> UserConfig:
    """Load the user TOML config, returning a safe ``UserConfig``.

    Never raises. Missing files yield ``source="default-missing"``;
    parse errors yield ``source="parse-error"`` with a redacted message;
    a successful load yields ``source="file"`` and the filtered values.
    """
    config_path = (path or default_user_config_path()).expanduser()
    if not config_path.exists():
        return UserConfig(
            path=config_path,
            exists=False,
            source=UserConfigSource.DEFAULT_MISSING,
            values={},
        )

    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        # Never let a malformed user config crash the CLI/TUI; surface a
        # short redacted reason for preflight to show.
        return UserConfig(
            path=config_path,
            exists=True,
            source=UserConfigSource.PARSE_ERROR,
            values={},
            parse_error=str(exc).splitlines()[0] if str(exc) else "parse error",
        )

    if not isinstance(raw, Mapping):
        return UserConfig(
            path=config_path,
            exists=True,
            source=UserConfigSource.PARSE_ERROR,
            values={},
            parse_error="top-level value must be a table",
        )

    return UserConfig(
        path=config_path,
        exists=True,
        source=UserConfigSource.FILE,
        values=_filter_values(raw),
    )


__all__ = [
    "NON_SENSITIVE_KEYS",
    "UserConfig",
    "UserConfigSource",
    "default_user_config_path",
    "load_user_config",
]
