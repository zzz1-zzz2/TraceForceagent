"""Provider-aware credential resolution.

This module is the single entry point that decides which API key and base URL
TraceForce should use. It explicitly refuses to "find any available key" — a
key only matches the configured provider, or the optional cross-provider
``TRACEFORCE_API_KEY`` override that the user has opted into.

The resolver never mutates ``os.environ``; the CLI loads explicit env files
via ``python-dotenv`` into an in-memory mapping and consults that mapping
together with a snapshot of ``os.environ``. This prevents a workspace
``.env`` from silently poisoning the configuration.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dotenv import dotenv_values


class CredentialSource(StrEnum):
    """How the resolved API key was sourced."""

    ENV_FILE = "env-file"
    PROCESS_ENV = "process-env"
    TRACEFORCE_DEFAULT = "traceforce-default"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """A known provider: where to find its key, default endpoint, default model."""

    id: str
    label: str
    default_base_url: str
    default_model: str
    credential_envs: tuple[str, ...]


# Built-in providers. ``credential_envs`` is searched in order; the first
# non-empty value wins. ``TRACEFORCE_API_KEY`` is **not** listed here — it is
# consulted as a cross-provider fallback only when the provider's own env
# vars are all unset (see :func:`resolve_credentials`).
PROVIDERS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        default_base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        credential_envs=("DEEPSEEK_API_KEY",),
    ),
    "openai": ProviderSpec(
        id="openai",
        label="OpenAI",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        credential_envs=("OPENAI_API_KEY",),
    ),
    "glm": ProviderSpec(
        id="glm",
        label="GLM (Zhipu)",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-flash",
        credential_envs=("GLM_API_KEY",),
    ),
    "qwen": ProviderSpec(
        id="qwen",
        label="Qwen (DashScope)",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-turbo",
        credential_envs=("QWEN_API_KEY",),
    ),
    "kimi": ProviderSpec(
        id="kimi",
        label="Kimi (Moonshot)",
        default_base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        credential_envs=("KIMI_API_KEY",),
    ),
}

# Provider IDs accepted by ``--provider``. Kept in one place so that CLI help,
# config parsing, and tests reference the same set.
PROVIDER_IDS: tuple[str, ...] = tuple(PROVIDERS.keys())

# The cross-provider override: only used when the provider's own key is
# absent. Documented behaviour, not an implicit fallback.
CROSS_PROVIDER_ENV = "TRACEFORCE_API_KEY"


@dataclass(frozen=True, slots=True)
class ResolvedCredentials:
    """Outcome of resolving credentials for a provider.

    ``api_key`` may be empty; callers should inspect ``source`` and ``present``
    before constructing an HTTP client.
    """

    provider: ProviderSpec
    api_key: str
    source: CredentialSource
    base_url: str
    model: str
    # Optional explicit source: which env var name (or env file) yielded the key.
    source_env: str | None = None

    @property
    def present(self) -> bool:
        return bool(self.api_key)


def _read_env_file(path: Path) -> dict[str, str]:
    """Read a ``.env`` file into a plain dict.

    ``python-dotenv`` does not mutate ``os.environ`` here, so the workspace's
    own ``.env`` cannot leak into subsequent subprocess / SDK calls.
    """
    if not path.exists():
        return {}
    values = dotenv_values(path, encoding="utf-8")
    # dotenv returns ``None`` for missing values; normalize to empty strings.
    return {k: ("" if v is None else str(v)) for k, v in values.items()}


def _select_key(
    spec: ProviderSpec,
    env_file_values: Mapping[str, str],
    process_env: Mapping[str, str],
) -> tuple[str, str | None, CredentialSource]:
    """Return ``(api_key, source_env_var, source_kind)`` for ``spec``.

    Order of precedence:

    1. Explicit env file (if provided by the user via ``--env-file``)
    2. Process environment
    3. ``TRACEFORCE_API_KEY`` cross-provider override — same precedence
       (env file first, then process env) but only consulted after the
       provider's own env vars are exhausted.
    """
    for env_name in spec.credential_envs:
        if env_name in env_file_values and env_file_values[env_name]:
            return env_file_values[env_name], env_name, CredentialSource.ENV_FILE
        if process_env.get(env_name):
            return process_env[env_name], env_name, CredentialSource.PROCESS_ENV

    # Cross-provider fallback. We treat TRACEFORCE_API_KEY as an explicit
    # user opt-in, so we only consume it when the provider-specific vars
    # are absent on both the env file and the process environment.
    if CROSS_PROVIDER_ENV in env_file_values and env_file_values[CROSS_PROVIDER_ENV]:
        return (
            env_file_values[CROSS_PROVIDER_ENV],
            CROSS_PROVIDER_ENV,
            CredentialSource.TRACEFORCE_DEFAULT,
        )
    if process_env.get(CROSS_PROVIDER_ENV):
        return (
            process_env[CROSS_PROVIDER_ENV],
            CROSS_PROVIDER_ENV,
            CredentialSource.TRACEFORCE_DEFAULT,
        )

    return "", None, CredentialSource.MISSING


def resolve_credentials(
    provider_id: str,
    *,
    env_file: Path | None = None,
    base_url: str | None = None,
    model: str | None = None,
    process_env: Mapping[str, str] | None = None,
) -> ResolvedCredentials:
    """Resolve credentials and endpoint for the requested provider.

    Parameters
    ----------
    provider_id:
        One of :data:`PROVIDER_IDS`. Unknown values raise ``ValueError`` —
        we deliberately do not silently fall back to a default provider
        because that would mask configuration mistakes.
    env_file:
        Optional explicit ``--env-file`` path. Only consulted if provided
        by the caller; the workspace's own ``.env`` is never auto-loaded.
    base_url / model:
        Optional explicit overrides; default to the provider's well-known
        endpoint and model.
    process_env:
        Optional explicit environment mapping for tests. Defaults to a
        snapshot of ``os.environ`` so we never observe mutations made by
        concurrent code paths.
    """
    if provider_id not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider_id!r}. "
            f"Available providers: {', '.join(PROVIDER_IDS)}."
        )

    spec = PROVIDERS[provider_id]
    env_file_values = _read_env_file(env_file) if env_file is not None else {}
    if process_env is None:
        # Snapshot ``os.environ`` to avoid leaking values written after the
        # call (or, more importantly, to avoid surprising tests).
        process_env = dict(os.environ)

    api_key, source_env, source_kind = _select_key(spec, env_file_values, process_env)

    return ResolvedCredentials(
        provider=spec,
        api_key=api_key,
        source=source_kind,
        base_url=base_url or spec.default_base_url,
        model=model or spec.default_model,
        source_env=source_env,
    )


__all__ = [
    "CROSS_PROVIDER_ENV",
    "CredentialSource",
    "PROVIDER_IDS",
    "PROVIDERS",
    "ProviderSpec",
    "ResolvedCredentials",
    "resolve_credentials",
]
