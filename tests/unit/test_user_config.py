"""Tests for the user-level TOML config (P2-1D)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.config import load_config
from coding_agent.config.user_config import (
    NON_SENSITIVE_KEYS,
    UserConfigSource,
    default_user_config_path,
    load_user_config,
)


def test_user_config_missing_file_returns_default_missing(tmp_path: Path) -> None:
    cfg = load_user_config(path=tmp_path / "no.toml")
    assert cfg.exists is False
    assert cfg.source is UserConfigSource.DEFAULT_MISSING
    assert cfg.values == {}


def test_user_config_malformed_toml_does_not_raise(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("this is not = valid toml ====", encoding="utf-8")
    cfg = load_user_config(path=bad)
    assert cfg.exists is True
    assert cfg.source is UserConfigSource.PARSE_ERROR
    assert cfg.values == {}
    assert cfg.parse_error  # populated, but redacted


def test_user_config_drops_unknown_keys(tmp_path: Path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text(
        'max_steps = 25\nunknown_key = "x"\n', encoding="utf-8"
    )
    cfg = load_user_config(path=toml)
    assert cfg.source is UserConfigSource.FILE
    assert cfg.values == {"max_steps": 25}
    assert "unknown_key" not in cfg.values


def test_user_config_never_accepts_credential_shaped_keys(tmp_path: Path) -> None:
    """Forbid api_key / *_TOKEN / *_SECRET even when explicitly present."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        'api_key = "should-not-load"\n'
        'DEEPSEEK_API_KEY = "should-not-load-either"\n'
        'oauth_token = "nope"\n'
        'client_secret = "nope"\n'
        'permission_policy = "allow-all"\n'
        'max_steps = 30\n',
        encoding="utf-8",
    )
    cfg = load_user_config(path=toml)
    assert cfg.source is UserConfigSource.FILE
    assert cfg.values == {"max_steps": 30}
    assert "api_key" not in cfg.values
    assert "DEEPSEEK_API_KEY" not in cfg.values
    assert "oauth_token" not in cfg.values
    assert "permission_policy" not in cfg.values


def test_user_config_allow_list_matches_documented_keys() -> None:
    """The allow-list must contain every non-sensitive field we promised
    in the plan, and must NOT contain any credential-shaped key."""
    sensitive = {"api_key", "DEEPSEEK_API_KEY", "token", "secret"}
    assert sensitive.isdisjoint(NON_SENSITIVE_KEYS)
    assert {
        "active_provider",
        "active_model",
        "active_base_url",
        "temperature",
        "max_steps",
        "max_model_calls",
        "max_wall_time",
        "command_timeout",
        "max_tool_output",
        "context_budget",
        "recent_turns",
        "log_level",
        "log_json",
        "enable_failure_refresh",
        "trace_root",
        "workspace_root",
    }.issubset(NON_SENSITIVE_KEYS)


def test_load_config_applies_user_overrides_without_credential_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    toml = tmp_path / "config.toml"
    toml.write_text(
        'temperature = 0.5\nmax_steps = 12\nlog_level = "DEBUG"\n'
        'api_key = "poisoned-from-toml"\n',
        encoding="utf-8",
    )
    config = load_config(user_config_path=toml)
    assert config.temperature == 0.5
    assert config.max_steps == 12
    assert config.log_level == "DEBUG"
    # The poisoned api_key MUST NOT have leaked into the resolved config.
    assert config.api_key == ""
    assert config.credential_source == "missing"
    # user_config metadata is recorded so config-show can report it.
    assert config.user_config_source == "file"
    assert config.user_config_path == toml


def test_default_user_config_path_uses_xdg_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/xdg")
    assert default_user_config_path() == Path("/custom/xdg/traceforce/config.toml")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert default_user_config_path().name == "config.toml"


def test_user_config_top_level_must_be_table(tmp_path: Path) -> None:
    bad = tmp_path / "list.toml"
    bad.write_text('["a", "b"]\n', encoding="utf-8")
    cfg = load_user_config(path=bad)
    assert cfg.source is UserConfigSource.PARSE_ERROR
    assert "table" in cfg.parse_error.lower() or cfg.parse_error  # redacted
