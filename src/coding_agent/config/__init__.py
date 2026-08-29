"""Configuration package.

Re-exports :class:`AgentConfig`, :func:`load_config`, and the provider
resolver surface so callers can write ``from coding_agent.config import
AgentConfig, load_config``.
"""

from coding_agent.config.config import AgentConfig, load_config
from coding_agent.config.provider_resolver import (
    CROSS_PROVIDER_ENV,
    PROVIDER_IDS,
    PROVIDERS,
    CredentialSource,
    ProviderSpec,
    ResolvedCredentials,
    resolve_credentials,
)

__all__ = [
    "AgentConfig",
    "CROSS_PROVIDER_ENV",
    "CredentialSource",
    "PROVIDER_IDS",
    "PROVIDERS",
    "ProviderSpec",
    "ResolvedCredentials",
    "load_config",
    "resolve_credentials",
]
