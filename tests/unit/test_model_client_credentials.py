"""ModelClient credential-loading tests (P0-0 hotfix)."""

from __future__ import annotations

import pytest

from coding_agent.config import AgentConfig, load_config
from coding_agent.model.client import MissingCredentialsError, ModelClient


def test_from_config_raises_missing_credentials_for_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRACEFORCE_API_KEY", raising=False)
    config = load_config()
    assert not config.api_key

    with pytest.raises(MissingCredentialsError) as exc_info:
        ModelClient.from_config(config)
    assert exc_info.value.provider == "deepseek"
    assert "DEEPSEEK_API_KEY" in exc_info.value.suggestion


def test_from_config_uses_resolved_key_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ModelClient no longer reads multiple env vars on its own."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-only")

    config = load_config(provider="openai")
    client = ModelClient.from_config(config)
    assert client.api_key == "openai-only"
    assert client.model == "gpt-4o-mini"
    assert client.base_url == "https://api.openai.com/v1"


def test_missing_credentials_error_str_mentions_provider() -> None:
    err = MissingCredentialsError(provider="glm", suggestion="set GLM_API_KEY")
    text = str(err)
    assert "glm" in text
    assert "GLM_API_KEY" in text


def test_from_config_does_not_silently_swallow_credentials() -> None:
    """A blank AgentConfig (no env, no env-file) must raise, not return a client."""
    config = AgentConfig()
    config.api_key = ""
    with pytest.raises(MissingCredentialsError):
        ModelClient.from_config(config)
