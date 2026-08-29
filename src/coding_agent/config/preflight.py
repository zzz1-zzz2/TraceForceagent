"""Unified preflight checks shared by CLI and TUI.

A preflight result is a list of named checks, each with an ``ok`` flag
and a short redacted detail line. The CLI renders one row per check and
exits non-zero when any hard check fails; the TUI renders the same lines
inside a single system notice without leaking the API key.

Only the :func:`run_preflight` function and the dataclasses it returns
are intended as the public surface — the individual check helpers are
module-private so we can add or reorder them without touching callers.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import urlparse

from coding_agent.config.provider_resolver import PROVIDERS
from coding_agent.config.user_config import UserConfigSource

if TYPE_CHECKING:
    from coding_agent.config import AgentConfig


# Imported lazily inside :func:`run_preflight` to avoid the circular
# dependency between :mod:`coding_agent.config` and this module. The
# caller already has ``config: AgentConfig`` in hand by then.


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    """One named preflight row."""

    name: str
    ok: bool
    detail: str

    def render(self) -> str:
        icon = "✓" if self.ok else "✗"
        return f"{icon} {self.name} · {self.detail}"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Aggregate preflight outcome.

    ``ok`` is True when every required check passed. ``warnings`` carries
    non-fatal rows (currently only the user-config parse error) so the
    caller can decide whether to surface them.
    """

    checks: tuple[PreflightCheck, ...]
    warnings: tuple[PreflightCheck, ...] = ()

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failing(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def failing_names(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.failing)

    def summary_lines(self) -> list[str]:
        """Return a list of formatted rows for terminal/TUI rendering.

        The order is hard checks first, then warnings. The format is the
        same as ``PreflightCheck.render`` and never includes the API key.
        """
        return [check.render() for check in self.checks] + [
            check.render() for check in self.warnings
        ]


_DEFAULT_CHECKS: Final[tuple[str, ...]] = (
    "provider",
    "base_url",
    "model",
    "credentials",
    "user_config",
    "workspace",
    "git",
    "rg",
)


_REQUIRED_TOOLS: Final[tuple[str, ...]] = ("git", "rg")


def _check_provider(config: AgentConfig) -> PreflightCheck:
    if config.active_provider in PROVIDERS:
        return PreflightCheck(
            name="provider",
            ok=True,
            detail=f"{config.active_provider}",
        )
    return PreflightCheck(
        name="provider",
        ok=False,
        detail=f"unknown provider {config.active_provider!r}",
    )


def _check_base_url(config: AgentConfig) -> PreflightCheck:
    url = (config.active_base_url or "").strip()
    if not url:
        return PreflightCheck(name="base_url", ok=False, detail="empty")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return PreflightCheck(
            name="base_url",
            ok=False,
            detail=f"invalid url {url!r}",
        )
    return PreflightCheck(name="base_url", ok=True, detail=parsed.netloc)


def _check_model(config: AgentConfig) -> PreflightCheck:
    model = (config.active_model or "").strip()
    if not model:
        return PreflightCheck(name="model", ok=False, detail="empty")
    return PreflightCheck(name="model", ok=True, detail=model)


def _check_credentials(
    config: AgentConfig, *, require: bool
) -> PreflightCheck | None:
    """Return the credentials check, or ``None`` when not required."""
    if not require:
        return None
    if config.api_key:
        # Render only the source/env pair; never echo key bytes.
        env = config.credential_env or "(unknown)"
        return PreflightCheck(
            name="credentials",
            ok=True,
            detail=f"resolved via {config.credential_source} from {env}",
        )
    return PreflightCheck(
        name="credentials",
        ok=False,
        detail="no API key resolved (use --env-file or set provider env var)",
    )


def _check_user_config(config: AgentConfig) -> PreflightCheck:
    """Hard check on user-config parse failure; soft warning otherwise."""
    source = config.user_config_source
    if source == UserConfigSource.PARSE_ERROR.value:
        return PreflightCheck(
            name="user_config",
            ok=False,
            detail=f"failed to parse {config.user_config_path}: "
            f"{config.user_config_parse_error or 'parse error'}",
        )
    return PreflightCheck(
        name="user_config",
        ok=True,
        detail=f"{source} ({config.user_config_path})",
    )


def _check_workspace(workspace: Path) -> PreflightCheck:
    if workspace.exists():
        if workspace.is_dir():
            return PreflightCheck(
                name="workspace",
                ok=True,
                detail=str(workspace),
            )
        return PreflightCheck(
            name="workspace",
            ok=False,
            detail=f"{workspace} exists but is not a directory",
        )
    # Try to create so a missing but creatable path is reported as ok
    # only when the caller has confirmed it (we avoid surprise writes).
    try:
        if workspace.parent.exists():
            return PreflightCheck(
                name="workspace",
                ok=True,
                detail=f"{workspace} (will be created)",
            )
    except OSError:
        pass
    return PreflightCheck(
        name="workspace",
        ok=False,
        detail=f"{workspace} does not exist",
    )


def _check_tool(tool: str) -> PreflightCheck:
    path = shutil.which(tool)
    if path:
        return PreflightCheck(name=tool, ok=True, detail=path)
    return PreflightCheck(
        name=tool,
        ok=False,
        detail=f"{tool} not on PATH",
    )


def run_preflight(
    config: AgentConfig,
    *,
    workspace: Path | None = None,
    require_credentials: bool = True,
    checks: Sequence[str] | None = None,
) -> PreflightResult:
    """Run the configured preflight checks against ``config``.

    Parameters
    ----------
    config:
        The :class:`AgentConfig` produced by :func:`load_config`.
    workspace:
        Optional workspace path. When provided, a workspace check is
        included; otherwise the check is skipped.
    require_credentials:
        When False, the credentials check is omitted so the TUI can run
        preflight on mount even before the user has typed a task.
    checks:
        Optional subset to run. Defaults to the standard set.
    """
    selected = set(checks) if checks is not None else set(_DEFAULT_CHECKS)
    rows: list[PreflightCheck] = []

    if "provider" in selected:
        rows.append(_check_provider(config))
    if "base_url" in selected:
        rows.append(_check_base_url(config))
    if "model" in selected:
        rows.append(_check_model(config))
    if "credentials" in selected:
        credentials = _check_credentials(config, require=require_credentials)
        if credentials is not None:
            rows.append(credentials)
    if "workspace" in selected and workspace is not None:
        rows.append(_check_workspace(workspace))
    for tool in _REQUIRED_TOOLS:
        if tool in selected:
            rows.append(_check_tool(tool))

    user_config_row = _check_user_config(config)
    if user_config_row.ok:
        return PreflightResult(checks=tuple(rows), warnings=(user_config_row,))
    rows.append(user_config_row)
    return PreflightResult(checks=tuple(rows))


__all__ = [
    "PreflightCheck",
    "PreflightResult",
    "run_preflight",
]
