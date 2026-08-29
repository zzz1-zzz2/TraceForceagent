"""CLI configuration loading tests (P0-0 hotfix).

These tests exercise the CLI's ``--env-file`` and ``--provider`` surface
without making real LLM calls. They use :class:`typer.testing.CliRunner`
to invoke the app and inspect both the rendered output and exit code.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from coding_agent.cli import app

runner = CliRunner()


def test_check_reports_missing_credentials_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("TRACEFORCE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=poisoned\n", encoding="utf-8")

    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "no API key resolved" in result.stdout
    # The workspace .env must NOT have leaked into the resolved config.
    assert "poisoned" not in result.stdout


def test_check_honors_explicit_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env_file = tmp_path / "traceforce.env"
    env_file.write_text("DEEPSEEK_API_KEY=clean-key\n", encoding="utf-8")

    result = runner.invoke(app, ["--env-file", str(env_file), "check"])
    assert result.exit_code == 0
    assert "env-file" in result.stdout
    assert "DEEPSEEK_API_KEY" in result.stdout


def test_check_rejects_unknown_env_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.env"
    result = runner.invoke(app, ["--env-file", str(missing), "check"])
    assert result.exit_code == 2
    assert "env-file not found" in result.stdout.lower()


def test_check_rejects_unknown_provider() -> None:
    result = runner.invoke(app, ["--provider", "bogus", "check"])
    assert result.exit_code == 2
    assert "Unknown provider" in result.stdout


def test_check_resolves_provider_specific_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    result = runner.invoke(app, ["--provider", "openai", "check"])
    assert result.exit_code == 0
    assert "openai" in result.stdout
    assert "OPENAI_API_KEY" in result.stdout
    assert "sk-openai" not in result.stdout  # masked


def test_check_provider_switch_ignores_other_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting keys for other providers must not satisfy the requested provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("TRACEFORCE_API_KEY", raising=False)

    result = runner.invoke(app, ["--provider", "glm", "check"])
    assert result.exit_code == 0
    assert "no API key resolved" in result.stdout


def test_config_show_prints_redacted_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-very-secret")

    result = runner.invoke(app, ["config-show"])
    assert result.exit_code == 0
    assert "deepseek" in result.stdout
    assert "sk-very-secret" not in result.stdout


def test_run_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a key, ``run`` exits non-zero with a clean message."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRACEFORCE_API_KEY", raising=False)

    result = runner.invoke(
        app, ["run", "--task", "noop", "--workspace", "/tmp/nope-zz-tf"]
    )
    assert result.exit_code == 1
    assert "no API key resolved" in result.stdout


def test_run_requires_task_or_task_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "task" in result.stdout.lower()
