"""P1-4：Trajectory 必须写到 ~/.traceforce/runs/,不能污染 workspace。

验证：
1) 默认行为：轨迹写到 ~/.traceforce/runs/<workspace_basename>/run_<id>/
2) 显式 trace_root 覆盖默认
3) workspace 目录里完全没有 `runs/` 子目录
4) workspace 被当作 git repo 时,`git status` 干净(没有未跟踪的 runs/)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from coding_agent.config import AgentConfig
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall
from coding_agent.trajectory.logger import TrajectoryLogger, _default_trace_root


def _model_resp(call_id, tool, args):
    return ModelResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name=tool, arguments=args)],
        finish_reason="tool_calls",
        usage=TokenUsage(),
    )


def _finish_resp(call_id, summary="done"):
    return ModelResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name="finish",
                             arguments={"summary": summary, "validation": "passed"})],
        finish_reason="tool_calls",
        usage=TokenUsage(),
    )


def _install_model(monkeypatch, responses):
    """把 ModelClient.generate 替换成返回 responses 队列。"""
    from coding_agent.model.client import ModelClient

    queue = list(responses)
    counter = {"n": 0}

    def _generate(self, messages, tools=None):
        if counter["n"] >= len(queue):
            return _finish_resp("overflow", "exhausted")
        r = queue[counter["n"]]
        counter["n"] += 1
        return r

    monkeypatch.setattr(ModelClient, "generate", _generate)
    return counter


class TestTrajectoryLayout:
    def test_default_root_is_home_traceforce(self):
        root = _default_trace_root()
        assert root == Path.home() / ".traceforce" / "runs"

    def test_logger_writes_under_workspace_basename(self, tmp_path):
        workspace = tmp_path / "my_repo"
        workspace.mkdir()
        (workspace / "a.txt").write_text("hi")
        logger = TrajectoryLogger(run_id="run_test_1", workspace=workspace)
        try:
            # 路径应当在 ~/.traceforce/runs/my_repo/run_test_1/
            assert logger.run_dir.parent.name == "my_repo"
            assert logger.run_dir.name == "run_test_1"
            assert logger.path.name == "trajectory.jsonl"
            # 但不应当在 workspace 里
            assert not (workspace / "runs").exists()
        finally:
            logger.close()

    def test_explicit_trace_root_overrides_default(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        custom_root = tmp_path / "alt_trace"
        logger = TrajectoryLogger(
            run_id="run_x", workspace=workspace, trace_root=custom_root
        )
        try:
            assert logger.run_dir.parent.parent == custom_root
            assert logger.run_dir.parent.name == "ws"
        finally:
            logger.close()

    def test_workspace_pollution_free_e2e(self, tmp_path, monkeypatch):
        """端到端跑一次 Agent,workspace 里不能出现 runs/。"""
        from coding_agent.agent.loop import run as agent_run

        workspace = tmp_path / "agent_workspace"
        workspace.mkdir()
        trace_root = tmp_path / "trace_root"
        cfg = AgentConfig(
            context_budget=8000,
            recent_turns=4,
            max_steps=10,
            max_model_calls=15,
            max_wall_time=30,
            command_timeout=10,
            workspace_root=workspace,
            trace_root=trace_root,
            enable_failure_refresh=False,
        )

        _install_model(monkeypatch, [
            _model_resp("cp", "apply_patch", {
                "path": "hello.py", "content": "print('hi')\n", "mode": "create",
            }),
            _finish_resp("cf", "wrote hello.py"),
        ])

        result = agent_run(task="make hello.py", workspace=workspace, config=cfg)

        # 1) workspace 下没有 runs/
        assert not (workspace / "runs").exists(), \
            f"workspace should not contain runs/, but found: {list((workspace / 'runs').iterdir())}"

        # 2) trajectory 写到了 trace_root
        assert result.trajectory_path is not None
        assert str(result.trajectory_path).startswith(str(trace_root))

        # 3) trajectory 文件存在并包含 model_call 事件
        assert result.trajectory_path.exists()
        events = [json.loads(l) for l in result.trajectory_path.open() if l.strip()]
        assert any(e["type"] == "model_call" for e in events)

    def test_workspace_remains_git_clean(self, tmp_path, monkeypatch):
        """workspace 初始化为 git repo 后,跑 Agent 不应留下 untracked runs/。"""
        from coding_agent.agent.loop import run as agent_run

        workspace = tmp_path / "git_ws"
        workspace.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=workspace, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=workspace, check=True)
        (workspace / "README.md").write_text("# repo")
        subprocess.run(["git", "add", "README.md"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"], cwd=workspace, check=True
        )

        trace_root = tmp_path / "trace_root2"
        cfg = AgentConfig(
            context_budget=8000,
            recent_turns=4,
            max_steps=10,
            max_model_calls=15,
            max_wall_time=30,
            command_timeout=10,
            workspace_root=workspace,
            trace_root=trace_root,
            enable_failure_refresh=False,
        )

        _install_model(monkeypatch, [
            _model_resp("cp", "apply_patch", {
                "path": "hello.py", "content": "x=1\n", "mode": "create",
            }),
            _finish_resp("cf", "ok"),
        ])

        agent_run(task="add hello.py", workspace=workspace, config=cfg)

        # git status 只应当显示 hello.py 的改动,没有 runs/
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace, capture_output=True, text=True, check=True,
        )
        porcelain = status.stdout
        assert "runs/" not in porcelain, \
            f"runs/ leaked into workspace git status:\n{porcelain}"
        assert "hello.py" in porcelain  # 真实改动在