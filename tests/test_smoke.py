"""Smoke test：CLI 能跑、能 help。"""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def test_cli_help():
    """`python -m coding_agent --help` 返回 0。"""
    result = subprocess.run(
        [sys.executable, "-m", "coding_agent", "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "coding-agent" in result.stdout.lower() or "run" in result.stdout.lower()


def test_cli_version():
    """`python -m coding_agent --version` 返回版本。"""
    result = subprocess.run(
        [sys.executable, "-m", "coding_agent", "--version"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


def test_imports():
    """主要模块都能 import。"""
    from coding_agent import __version__
    from coding_agent.agent import AgentState, StopReason, TerminationController
    from coding_agent.model import ModelClient, OpenAICompatibleParser
    from coding_agent.context import ContextManager
    from coding_agent.tools import Tool, ToolRegistry, default_registry
    from coding_agent.runtime import LocalRuntime
    from coding_agent.trajectory import TrajectoryLogger
    from coding_agent.recovery import FailureAwareRefresher

    assert __version__ == "0.1.0"
    assert callable(TerminationController)
    assert callable(default_registry)