"""FailureAwareRefresher 接入 AgentLoop 的集成测试 + 单元测试。

P1-3 关键回归：当测试失败时，Active Context 应当收到 ~5 行的 Failure Snapshot，
而不是几百行的 traceback。FailureAwareRefresher 必须被 loop 实际调用。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coding_agent.agent.state import AgentState
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager
from coding_agent.model.types import ToolResult
from coding_agent.recovery.failure_refresh import FailureAwareRefresher


class TestFailureAwareRefresher:
    def test_disabled_passes_through(self):
        obs = ToolResult.fail("x", is_validation_failure=True)
        refresher = FailureAwareRefresher(enabled=False)
        assert refresher.maybe_refresh(AgentState.initialize(task="t", workspace=Path("/tmp")), obs) is obs

    def test_non_validation_passes_through(self):
        obs = ToolResult.fail("x", is_validation_failure=False)
        refresher = FailureAwareRefresher(enabled=True)
        out = refresher.maybe_refresh(AgentState.initialize(task="t", workspace=Path("/tmp")), obs)
        assert out is obs

    def test_validation_failure_returns_snapshot(self, tmp_path):
        long_traceback = "x" * 5000 + "\n" + \
            "FAILED tests/test_x.py::test_y - AssertionError: 1 != 2\n" + "x" * 5000
        obs = ToolResult.fail(
            long_traceback,
            is_validation_failure=True,
            summary="pytest failed",
        )
        state = AgentState.initialize(task="t", workspace=tmp_path)
        state.record_modified("foo.py")

        refresher = FailureAwareRefresher(enabled=True)
        out = refresher.maybe_refresh(state, obs)

        assert out is not obs  # 已替换
        assert "FAILED" in out.content
        assert "foo.py" in out.content
        # snapshot 比原 traceback 短很多
        assert len(out.content) < len(long_traceback) // 5


class TestRefresherInLoop:
    """FailureAwareRefresher 必须真正被 AgentLoop 调用。"""

    @pytest.fixture
    def fake_workspace(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
        tests_dir = workspace / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_fail.py").write_text(
            "def test_fail():\n    assert 1 == 2\n"
        )
        return workspace

    @pytest.fixture
    def config(self, fake_workspace, tmp_path):
        return AgentConfig(
            context_budget=8000,
            recent_turns=4,
            max_steps=15,
            max_model_calls=20,
            max_wall_time=30,
            command_timeout=15,
            workspace_root=fake_workspace,
            trace_root=tmp_path / "trace",
            enable_failure_refresh=True,
        )

    @pytest.fixture
    def patch_model(self, monkeypatch):
        from coding_agent.model.client import ModelClient
        from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall

        class FakeModel:
            def __init__(self, responses):
                self.responses = list(responses)
                self.call_count = 0
                self.generate = self._generate

            def _generate(self, messages, tools=None):
                if self.call_count >= len(self.responses):
                    return ModelResponse(
                        content="",
                        tool_calls=[ToolCall(id="c", name="finish",
                                             arguments={"summary": "exhausted"})],
                        finish_reason="tool_calls",
                        usage=TokenUsage(),
                    )
                r = self.responses[self.call_count]
                self.call_count += 1
                return r

        def _patch(responses):
            fake = FakeModel(responses)

            def fake_from_config(cls, _cfg):
                instance = cls.__new__(cls)
                instance._fake = fake
                instance.generate = fake.generate
                return instance

            monkeypatch.setattr(ModelClient, "from_config", classmethod(fake_from_config))
            return fake

        return _patch

    def test_loop_uses_refresher_for_failing_tests(
        self, fake_workspace, config, patch_model
    ):
        """跑一个会失败的 pytest，下一轮 model 收到的 tool message 应该是 snapshot。"""
        from coding_agent.agent.loop import run as agent_run
        from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall

        # 1) apply_patch 一个文件
        # 2) 跑 pytest（会失败）
        # 3) finish（FinishPolicy 会拒绝，因为 validation failed）
        # 第 2 步之后，refresher 应替换 observation 为 snapshot
        patch_model([
            ModelResponse(
                content="",
                tool_calls=[ToolCall(id="cp", name="apply_patch",
                                     arguments={"path": "broken.py",
                                                "content": "x=1\n",
                                                "mode": "create"})],
                finish_reason="tool_calls",
                usage=TokenUsage(),
            ),
            ModelResponse(
                content="",
                tool_calls=[ToolCall(id="cr", name="run_command",
                                     arguments={"command": "pytest -q"})],
                finish_reason="tool_calls",
                usage=TokenUsage(),
            ),
            ModelResponse(
                content="",
                tool_calls=[ToolCall(id="cf", name="finish",
                                     arguments={"summary": "tried", "validation": "failed"})],
                finish_reason="tool_calls",
                usage=TokenUsage(),
            ),
        ])

        result = agent_run(
            task="修复 broken.py 并跑测试",  # 中文 + "修复" → existing_repository
            workspace=fake_workspace,
            config=config,
        )

        # finish 被拒绝（validation fail），max_consecutive_errors 触发 stop
        assert result.stop_reason != "finish"

        # P1-4：trajectory 路径走 result.trajectory_path,不再读 workspace/runs
        traj_path = result.trajectory_path
        import json
        events = [json.loads(l) for l in traj_path.open() if l.strip()]
        tool_events = [e for e in events if e["type"] == "tool_call"]
        # 第二个 tool_call 是 pytest 失败的，应当 is_validation_failure=True
        pytest_event = next(e for e in tool_events if e["tool"] == "run_command")
        assert pytest_event["is_validation_failure"] is True

        # 验证 summary 是 FAIL 形式
        assert pytest_event["result_summary"].startswith("FAIL:")

        # workspace 干净,没有 runs/
        assert not (fake_workspace / "runs").exists()

    def test_refresher_disabled_passes_full_observation(
        self, fake_workspace, patch_model, tmp_path
    ):
        """enable_failure_refresh=False 时不调用 refresher，保留完整 traceback。"""
        from coding_agent.agent.loop import run as agent_run
        from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall

        config = AgentConfig(
            context_budget=8000,
            recent_turns=4,
            max_steps=15,
            max_model_calls=20,
            max_wall_time=30,
            command_timeout=15,
            workspace_root=fake_workspace,
            trace_root=tmp_path / "trace",
            enable_failure_refresh=False,
        )

        patch_model([
            ModelResponse(
                content="",
                tool_calls=[ToolCall(id="cp", name="apply_patch",
                                     arguments={"path": "broken.py",
                                                "content": "x=1\n",
                                                "mode": "create"})],
                finish_reason="tool_calls",
                usage=TokenUsage(),
            ),
            ModelResponse(
                content="",
                tool_calls=[ToolCall(id="cr", name="run_command",
                                     arguments={"command": "pytest -q"})],
                finish_reason="tool_calls",
                usage=TokenUsage(),
            ),
        ])

        result = agent_run(
            task="disable refresher test",
            workspace=fake_workspace,
            config=config,
        )

        # P1-4：从 result.trajectory_path 读
        traj_path = result.trajectory_path
        import json
        events = [json.loads(l) for l in traj_path.open() if l.strip()]
        tool_events = [e for e in events if e["type"] == "tool_call"]
        pytest_event = next(e for e in tool_events if e["tool"] == "run_command")
        # 没 FAIL  prefix（因为 refresher disabled）
        assert not pytest_event["result_summary"].startswith("FAIL:")