"""CLI smoke tests for preflight and config-path commands (P2-1D)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coding_agent.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _fake_required_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"git", "rg"} else None,
    )


def test_check_with_env_file_passes_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env_file = tmp_path / "traceforce.env"
    env_file.write_text("DEEPSEEK_API_KEY=clean-key\n", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = runner.invoke(
        app,
        [
            "--env-file",
            str(env_file),
            "--provider",
            "deepseek",
            "check",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.stdout
    for name in ("provider", "base_url", "model", "credentials", "git", "rg"):
        assert name in result.stdout


def test_check_fails_when_rg_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = runner.invoke(app, ["check", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert "rg" in result.stdout


def test_check_renders_masked_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env_file = tmp_path / "traceforce.env"
    env_file.write_text("DEEPSEEK_API_KEY=sk-very-secret-not-real\n", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = runner.invoke(
        app,
        [
            "--env-file",
            str(env_file),
            "check",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0
    assert "sk-very-secret-not-real" not in result.stdout
    # The masked prefix should be visible.
    assert "sk-ve" in result.stdout or "***" in result.stdout


def test_config_path_prints_user_config_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    result = runner.invoke(app, ["config-path"])
    assert result.exit_code == 0
    assert "config.toml" in result.stdout
    assert "exists" in result.stdout or "missing" in result.stdout


def test_config_show_includes_user_config_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    result = runner.invoke(app, ["config-show"])
    assert result.exit_code == 0
    assert "user_config" in result.stdout
