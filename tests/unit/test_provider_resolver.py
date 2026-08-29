"""Provider-aware credential resolution tests (P0-0 hotfix)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.config.provider_resolver import (
    CROSS_PROVIDER_ENV,
    PROVIDER_IDS,
    PROVIDERS,
    CredentialSource,
    resolve_credentials,
)


@pytest.mark.parametrize("provider_id", PROVIDER_IDS)
def test_each_provider_finds_its_own_env_var(
    provider_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting only the active provider's env var resolves a key."""
    monkeypatch.delenv(CROSS_PROVIDER_ENV, raising=False)
    spec = PROVIDERS[provider_id]
    env_name = spec.credential_envs[0]
    monkeypatch.setenv(env_name, f"key-{provider_id}")
    # Other providers should be ignored.
    for other in PROVIDER_IDS:
        if other == provider_id:
            continue
        other_name = PROVIDERS[other].credential_envs[0]
        monkeypatch.delenv(other_name, raising=False)

    result = resolve_credentials(provider_id)
    assert result.present
    assert result.api_key == f"key-{provider_id}"
    assert result.source == CredentialSource.PROCESS_ENV
    assert result.source_env == env_name
    assert result.base_url == spec.default_base_url
    assert result.model == spec.default_model


def test_unknown_provider_rejected() -> None:
    """Unknown provider ids must not silently fall back to a default."""
    with pytest.raises(ValueError):
        resolve_credentials("not-a-real-provider")


def test_env_file_takes_precedence_over_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit --env-file beats the process environment."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-shell")
    env_file = tmp_path / "traceforce.env"
    env_file.write_text("DEEPSEEK_API_KEY=from-file\n", encoding="utf-8")

    result = resolve_credentials("deepseek", env_file=env_file)
    assert result.api_key == "from-file"
    assert result.source == CredentialSource.ENV_FILE
    assert result.source_env == "DEEPSEEK_API_KEY"


def test_env_file_does_not_mutate_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading an env file via the resolver must not leak into os.environ."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env_file = tmp_path / "traceforce.env"
    env_file.write_text("DEEPSEEK_API_KEY=secret\n", encoding="utf-8")

    resolve_credentials("deepseek", env_file=env_file)
    import os
    assert os.environ.get("DEEPSEEK_API_KEY") is None


def test_cross_provider_fallback_used_only_when_provider_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TRACEFORCE_API_KEY`` is only consulted when the provider's own vars are absent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(CROSS_PROVIDER_ENV, "universal")

    result = resolve_credentials("openai")
    assert result.api_key == "universal"
    assert result.source == CredentialSource.TRACEFORCE_DEFAULT
    assert result.source_env == CROSS_PROVIDER_ENV


def test_cross_provider_fallback_does_not_override_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider-specific key wins over the cross-provider override."""
    monkeypatch.setenv("OPENAI_API_KEY", "provider-key")
    monkeypatch.setenv(CROSS_PROVIDER_ENV, "universal")

    result = resolve_credentials("openai")
    assert result.api_key == "provider-key"
    assert result.source_env == "OPENAI_API_KEY"


def test_missing_key_returns_missing_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key, no leak: the resolver returns a clean MISSING result."""
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv(CROSS_PROVIDER_ENV, raising=False)

    result = resolve_credentials("kimi")
    assert result.api_key == ""
    assert result.source == CredentialSource.MISSING
    assert not result.present
    assert result.base_url == PROVIDERS["kimi"].default_base_url


def test_explicit_base_url_and_model_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Callers can override the resolved endpoint and model name."""
    monkeypatch.setenv("GLM_API_KEY", "glm-secret")
    result = resolve_credentials(
        "glm",
        base_url="https://self-hosted.example/v1",
        model="glm-4-airx",
    )
    assert result.base_url == "https://self-hosted.example/v1"
    assert result.model == "glm-4-airx"


def test_explicit_process_env_used_for_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests can pass an explicit env mapping instead of os.environ."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    result = resolve_credentials(
        "deepseek",
        process_env={"DEEPSEEK_API_KEY": "scoped"},
    )
    assert result.api_key == "scoped"
    assert result.source_env == "DEEPSEEK_API_KEY"
    assert result.source == CredentialSource.PROCESS_ENV
