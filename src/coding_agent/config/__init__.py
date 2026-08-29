"""Configuration package.

Re-exports :class:`AgentConfig`, :func:`load_config`, and the provider
resolver surface so callers can write ``from coding_agent.config import
AgentConfig, load_config``.
"""

from coding_agent.config.config import AgentConfig, load_config
from coding_agent.config.preflight import PreflightCheck, PreflightResult, run_preflight
from coding_agent.config.provider_resolver import (
    CROSS_PROVIDER_ENV,
    PROVIDER_IDS,
    PROVIDERS,
    CredentialSource,
    ProviderProfile,
    ProviderSpec,
    ResolvedCredentials,
    resolve_credentials,
)
from coding_agent.config.user_config import (
    NON_SENSITIVE_KEYS,
    UserConfig,
    UserConfigSource,
    default_user_config_path,
    load_user_config,
)

__all__ = [
    "AgentConfig",
    "CROSS_PROVIDER_ENV",
    "CredentialSource",
    "NON_SENSITIVE_KEYS",
    "PROVIDER_IDS",
    "PROVIDERS",
    "PreflightCheck",
    "PreflightResult",
    "ProviderProfile",
    "ProviderSpec",
    "ResolvedCredentials",
    "UserConfig",
    "UserConfigSource",
    "default_user_config_path",
    "load_config",
    "load_user_config",
    "resolve_credentials",
    "run_preflight",
]
