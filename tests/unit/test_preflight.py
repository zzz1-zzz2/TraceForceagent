"""Tests for the unified preflight module (P2-1D)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from coding_agent.config import AgentConfig, run_preflight
from coding_agent.config.preflight import PreflightCheck
from coding_agent.config.provider_resolver import CredentialSource


@pytest.fixture(autouse=True)
def _fake_required_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"git", "rg"} else None,
    )


def _make_config(**overrides: object) -> AgentConfig:
    values: dict[str, object] = {
        "active_provider": "deepseek",
        "active_model": "deepseek-chat",
        "active_base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-fake",
        "credential_source": CredentialSource.ENV_FILE.value,
        "credential_env": "DEEPSEEK_API_KEY",
        "user_config_source": "default-missing",
    }
    values.update(overrides)
    return AgentConfig(**values)  # type: ignore[arg-type]


def test_preflight_passes_for_full_configuration(tmp_path: Path) -> None:
    config = _make_config()
    result = run_preflight(config, workspace=tmp_path)
    assert result.ok
    assert all(check.ok for check in result.checks)
    # The user_config success is reported as a soft warning, not a hard fail.
    assert any(check.name == "user_config" for check in result.warnings)


def test_preflight_fails_when_credentials_missing(tmp_path: Path) -> None:
    config = _make_config(api_key="", credential_source=CredentialSource.MISSING.value)
    result = run_preflight(config, workspace=tmp_path)
    assert not result.ok
    assert "credentials" in result.failing_names()


def test_preflight_can_skip_credentials_check() -> None:
    config = _make_config(api_key="")
    result = run_preflight(config, require_credentials=False)
    assert "credentials" not in {check.name for check in result.checks}
    assert result.ok


def test_preflight_rejects_unknown_provider() -> None:
    config = _make_config()
    # Bypass pydantic literal validation so we exercise the preflight path
    # (the CLI normally rejects unknown providers before reaching here).
    object.__setattr__(config, "active_provider", "bogus")
    result = run_preflight(config, require_credentials=False)
    assert "provider" in result.failing_names()


def test_preflight_rejects_invalid_base_url() -> None:
    config = _make_config(active_base_url="")
    result = run_preflight(config, require_credentials=False)
    assert "base_url" in result.failing_names()

    config = _make_config(active_base_url="not-a-url")
    result = run_preflight(config, require_credentials=False)
    assert "base_url" in result.failing_names()


def test_preflight_rejects_empty_model() -> None:
    config = _make_config(active_model="")
    result = run_preflight(config, require_credentials=False)
    assert "model" in result.failing_names()


def test_preflight_reports_missing_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    config = _make_config()
    result = run_preflight(config, require_credentials=False)
    assert "rg" in result.failing_names()
    assert "git" in result.failing_names()


def test_preflight_workspace_check_creates_or_skips(tmp_path: Path) -> None:
    config = _make_config()
    existing = tmp_path / "ws"
    existing.mkdir()
    result = run_preflight(config, workspace=existing)
    assert any(
        check.name == "workspace" and check.ok for check in result.checks
    )

    # Non-existent parent directory: should fail because we cannot create it.
    missing = tmp_path / "no-parent" / "ws"
    result = run_preflight(config, workspace=missing)
    assert "workspace" in result.failing_names()


def test_preflight_user_config_parse_error_is_hard_fail(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("not = valid ====", encoding="utf-8")
    from coding_agent.config import load_config

    config = load_config(user_config_path=bad)
    result = run_preflight(config, require_credentials=False)
    assert "user_config" in result.failing_names()


def test_preflight_summary_lines_never_leak_key() -> None:
    config = _make_config(api_key="sk-very-secret-leak-test")
    result = run_preflight(config, require_credentials=True)
    rendered = "\n".join(result.summary_lines())
    assert "sk-very-secret-leak-test" not in rendered
    # The source/env pair IS rendered (without the key bytes).
    assert "credentials" in rendered


def test_preflight_check_render_format() -> None:
    assert PreflightCheck(name="x", ok=True, detail="y").render() == "✓ x · y"
    assert PreflightCheck(name="x", ok=False, detail="y").render() == "✗ x · y"


def test_preflight_failing_names_lists_only_failures() -> None:
    config = _make_config(api_key="")
    result = run_preflight(config, require_credentials=True)
    failing_names = result.failing_names()
    assert "credentials" in failing_names
    for check in result.checks:
        if check.ok:
            assert check.name not in failing_names


def test_preflight_can_run_subset_of_checks() -> None:
    config = _make_config(api_key="")
    result = run_preflight(
        config, require_credentials=True, checks=("provider", "model")
    )
    names = {check.name for check in result.checks}
    assert names == {"provider", "model"}
    assert result.ok
