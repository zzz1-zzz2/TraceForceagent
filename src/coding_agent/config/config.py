"""Agent configuration: Pydantic Settings schema and :func:`load_config`.

Design notes (P0-0 hotfix):

* The workspace's own ``.env`` is **never** auto-loaded. Pydantic Settings
  is told ``env_file=None`` so a stray ``.env`` in the target repository
  cannot override credentials, model, base URL, trace root, or any other
  security-relevant field.
* Credentials and the active provider are resolved via
  :mod:`coding_agent.config.provider_resolver`, which never falls back to
  "the first key we find" and never reads ``os.environ`` mutably.
* :func:`load_config` accepts ``env_file``, ``provider``, ``base_url`` and
  ``model`` overrides — both the CLI and the TUI go through this single
  entry point so there is exactly one place that decides what the agent
  will use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from coding_agent.config.provider_resolver import (
    CredentialSource,
    ResolvedCredentials,
    resolve_credentials,
)


class AgentConfig(BaseSettings):
    """Runtime configuration for the coding agent.

    Sensitive fields (api_key, active_provider, active_base_url, trace_root,
    benchmark_mode, etc.) are populated exclusively through :func:`load_config`,
    which reads the explicit ``--env-file`` (if any) and the process
    environment via :func:`resolve_credentials`. The constructor here does
    not auto-load any file.
    """

    model_config = SettingsConfigDict(
        # CRITICAL: do not auto-load the workspace's .env. Sensitive fields
        # come from explicit --env-file / process env via load_config().
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Provider / model ---
    active_provider: Literal["deepseek", "openai", "glm", "qwen", "kimi"] = Field(
        default="deepseek",
        description="Active provider id (see coding_agent.config.provider_resolver).",
    )
    active_model: str = Field(
        default="deepseek-chat",
        description="Currently selected model. Overridden by provider default "
        "when load_config() resolves credentials.",
    )
    active_base_url: str = Field(
        default="https://api.deepseek.com/v1",
        description="Currently selected OpenAI-compatible base URL. Overridden by "
        "provider default when load_config() resolves credentials.",
    )
    api_key: str = Field(
        default="",
        description="Resolved API key. Populated by load_config(); not loaded "
        "from any file automatically.",
    )
    # Source of the resolved api_key. One of CredentialSource values.
    credential_source: str = Field(
        default=CredentialSource.MISSING.value,
        description="Where the resolved API key came from (env-file / "
        "process-env / traceforce-default / missing).",
    )
    credential_env: str = Field(
        default="",
        description="The env var name (or env-file key) that yielded the API key.",
    )
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # --- Agent behaviour ---
    max_steps: int = Field(default=50, gt=0)
    max_model_calls: int = Field(default=80, gt=0)
    max_wall_time: int = Field(default=1800, gt=0, description="seconds")
    command_timeout: int = Field(default=60, gt=0, description="per-shell-command timeout")
    max_tool_output: int = Field(default=50000, gt=0, description="bytes")

    # --- Context ---
    context_budget: int = Field(default=32000, gt=0, description="Active Context token cap")
    recent_turns: int = Field(default=10, gt=0, description="Recent Interaction turn cap")

    # --- Mode switches ---
    enable_failure_refresh: bool = Field(default=True)
    benchmark_mode: bool = Field(default=False, description="Disables interactive flows")

    # --- Logging ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_json: bool = Field(default=True)

    # --- Workspace ---
    workspace_root: Path = Field(default=Path("./workspace"))

    # --- Trajectory ---
    # Default to ~/.traceforce/runs/ rather than workspace/runs/ to keep
    # the target repo clean. Only env (or load_config) overrides it.
    trace_root: Path = Field(default=Path.home() / ".traceforce" / "runs")


def load_config(
    *,
    env_file: str | Path | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> AgentConfig:
    """Build an :class:`AgentConfig` with credentials resolved in one place.

    Resolution rules (see :func:`resolve_credentials`):

    * The workspace ``.env`` is **not** loaded.
    * ``--env-file <path>``, if provided, is parsed into an in-memory map;
      values take precedence over the process environment but never leak
      into ``os.environ``.
    * The provider is selected from the explicit ``provider`` override,
      the ``ACTIVE_PROVIDER`` env var, or the default (``deepseek``).
    * Only that provider's own credential env vars are consulted; the
      ``TRACEFORCE_API_KEY`` cross-provider override is consulted last.
    * If no key can be resolved, ``api_key`` is empty and
      ``credential_source`` is ``missing``; callers (CLI/TUI) decide whether
      that is fatal.
    """
    # 1. Pydantic-settings: only non-sensitive fields like ACTIVE_PROVIDER,
    #    ACTIVE_MODEL, ACTIVE_BASE_URL, MAX_STEPS, etc. (no api_key).
    #    We construct directly without an env file so the workspace .env
    #    never participates.
    config = AgentConfig()

    # 2. Provider selection: explicit override wins, then ACTIVE_PROVIDER
    #    from process env, then the field default.
    import os as _os

    provider_id = provider or _os.environ.get("ACTIVE_PROVIDER") or config.active_provider

    # 3. Resolve credentials through the single entry point.
    env_file_path = Path(env_file).expanduser() if env_file else None
    resolved: ResolvedCredentials = resolve_credentials(
        provider_id,
        env_file=env_file_path,
        base_url=base_url,
        model=model,
    )

    # 4. Stamp the resolved values back onto the config. We intentionally
    #    overwrite the pydantic defaults so a workspace .env could not have
    #    poisoned them earlier.
    config.active_provider = resolved.provider.id  # type: ignore[assignment]
    config.active_base_url = resolved.base_url
    config.active_model = resolved.model
    config.api_key = resolved.api_key
    config.credential_source = resolved.source.value
    config.credential_env = resolved.source_env or ""

    return config


__all__ = [
    "AgentConfig",
    "load_config",
]
