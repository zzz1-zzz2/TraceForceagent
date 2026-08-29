"""Tests for :func:`coding_agent.config.load_config` (P0-0 hotfix)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.config import load_config
from coding_agent.config.provider_resolver import (
    CROSS_PROVIDER_ENV,
    PROVIDERS,
    CredentialSource,
)


def test_load_config_does_not_auto_load_workspace_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stray workspace .env must not influence the resolved config."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=poisoned\n", encoding="utf-8")

    config = load_config()
    assert config.api_key == ""
    assert config.credential_source == CredentialSource.MISSING.value


def test_load_config_honors_explicit_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env_file = tmp_path / "traceforce.env"
    env_file.write_text("DEEPSEEK_API_KEY=clean\n", encoding="utf-8")

    config = load_config(env_file=env_file)
    assert config.api_key == "clean"
    assert config.credential_source == CredentialSource.ENV_FILE.value
    assert config.credential_env == "DEEPSEEK_API_KEY"


def test_load_config_provider_override_changes_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    config = load_config(provider="openai")
    assert config.active_provider == "openai"
    assert config.active_base_url == PROVIDERS["openai"].default_base_url
    assert config.active_model == PROVIDERS["openai"].default_model
    assert config.api_key == "sk-openai"


def test_load_config_picks_provider_specific_key_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-provider keys must not bleed into a different provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv(CROSS_PROVIDER_ENV, "universal")

    # Provider is deepseek; only DEEPSEEK_API_KEY and the cross-provider fallback
    # are consulted. OpenAI's key is irrelevant.
    config = load_config(provider="deepseek")
    assert config.api_key == "deepseek-key"
    assert config.credential_env == "DEEPSEEK_API_KEY"


def test_load_config_uses_cross_provider_when_provider_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv(CROSS_PROVIDER_ENV, "universal")

    config = load_config(provider="deepseek")
    assert config.api_key == "universal"
    assert config.credential_source == CredentialSource.TRACEFORCE_DEFAULT.value
    assert config.credential_env == CROSS_PROVIDER_ENV


def test_load_config_rejects_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    with pytest.raises(ValueError):
        load_config(provider="not-a-provider")


def test_load_config_active_provider_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When --provider is not given, ACTIVE_PROVIDER selects the provider."""
    monkeypatch.setenv("ACTIVE_PROVIDER", "glm")
    monkeypatch.setenv("GLM_API_KEY", "glm-key")

    config = load_config()
    assert config.active_provider == "glm"
    assert config.api_key == "glm-key"
    assert config.active_base_url == PROVIDERS["glm"].default_base_url


def test_load_config_explicit_base_url_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")

    config = load_config(base_url="https://example/v1", model="custom-model")
    assert config.active_base_url == "https://example/v1"
    assert config.active_model == "custom-model"
