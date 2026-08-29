"""Tests for the ProviderProfile alias and credential-freedom contract."""

from __future__ import annotations

from coding_agent.config.provider_resolver import (
    CredentialSource,
    ProviderProfile,
    ProviderSpec,
    ResolvedCredentials,
    resolve_credentials,
)


def test_provider_profile_is_an_alias_for_resolved_credentials() -> None:
    """`ProviderProfile` is the canonical name; the old name still resolves."""
    assert ProviderProfile is ResolvedCredentials


def test_resolve_credentials_returns_provider_profile_shape(
    monkeypatch: object,
) -> None:
    """The returned object exposes the documented profile fields."""
    result = resolve_credentials(
        "deepseek",
        env_file=None,
        base_url=None,
        model=None,
        process_env={"DEEPSEEK_API_KEY": "sk-fake"},
    )
    assert isinstance(result, ProviderProfile)
    assert isinstance(result.provider, ProviderSpec)
    assert result.api_key == "sk-fake"
    assert result.source is CredentialSource.PROCESS_ENV
    assert result.source_env == "DEEPSEEK_API_KEY"
    assert result.base_url == "https://api.deepseek.com/v1"
    assert result.model == "deepseek-chat"
    assert result.present is True


def test_resolve_credentials_with_no_key_still_returns_profile() -> None:
    result = resolve_credentials(
        "deepseek", env_file=None, process_env={}
    )
    assert isinstance(result, ProviderProfile)
    assert result.api_key == ""
    assert result.source is CredentialSource.MISSING
    assert result.present is False


def test_provider_profile_does_not_expose_key_when_missing() -> None:
    """The redacted contract: an empty api_key is exposed; a non-empty one is
    never silently truncated or masked by the resolver."""
    result = resolve_credentials("deepseek", env_file=None, process_env={})
    assert result.api_key == ""
    assert result.source_env is None
