"""CLI smoke tests for the installable Alpha boundary."""

import subprocess
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_package_metadata_and_console_scripts() -> None:
    """The Alpha distribution exposes the canonical and compatibility names."""
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    assert project["name"] == "traceforce-agent"
    assert project["version"] == "0.1.0a1"
    assert project["authors"] == [{"name": "zzz1-zzz2"}]
    assert project["license"] == {"file": "LICENSE"}
    assert project["scripts"] == {
        "tracef": "coding_agent.cli:app",
        "traceF": "coding_agent.cli:app",
        "traceforce": "coding_agent.cli:app",
        "coding-agent": "coding_agent.cli:app",
    }
    assert (PROJECT_ROOT / "LICENSE").is_file()


def test_cli_help() -> None:
    """`python -m coding_agent --help` 返回 0。"""
    result = subprocess.run(
        [sys.executable, "-m", "coding_agent", "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "tracef" in result.stdout.lower() or "run" in result.stdout.lower()


def test_cli_version() -> None:
    """`python -m coding_agent --version` 返回版本。"""
    result = subprocess.run(
        [sys.executable, "-m", "coding_agent", "--version"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "0.1.0a1" in result.stdout


def test_imports() -> None:
    """主要模块都能 import。"""
    from coding_agent import __version__
    from coding_agent.agent import AgentState, StopReason, TerminationController
    from coding_agent.context import ContextManager
    from coding_agent.model import ModelClient, OpenAICompatibleParser
    from coding_agent.recovery import FailureAwareRefresher
    from coding_agent.runtime import LocalRuntime
    from coding_agent.tools import Tool, ToolRegistry, default_registry
    from coding_agent.trajectory import TrajectoryLogger

    assert __version__ == "0.1.0a1"
    assert callable(AgentState)
    assert callable(StopReason)
    assert callable(TerminationController)
    assert callable(ModelClient)
    assert callable(OpenAICompatibleParser)
    assert callable(ContextManager)
    assert callable(Tool)
    assert callable(ToolRegistry)
    assert callable(default_registry)
    assert callable(LocalRuntime)
    assert callable(TrajectoryLogger)
    assert callable(FailureAwareRefresher)
