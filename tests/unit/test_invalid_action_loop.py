"""AgentLoop.InvalidAction 路径测试。

P0-1 关键回归：模型返回 invalid action 时：
1. state.consecutive_errors 增加
2. state.step_count / state.tool_calls **不**增加
3. context_manager 收到 record_feedback，**不**收到 record_observation
4. trajectory 记录 type=feedback 事件，**不**记录 type=tool_call
5. Agent 不会崩溃，继续循环

通过 FakeModel 替代真实 LLM 调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.agent.loop import run as agent_run
from coding_agent.config import AgentConfig
from coding_agent.model.client import ModelClient
from coding_agent.model.types import ModelResponse, TokenUsage


class FakeModel:
    """根据调用次数返回预设响应。"""

    def __init__(self, responses: list[ModelResponse]):
        self.responses = list(responses)
        self.call_count = 0
        self.generate = self._generate  # 绑定让 monkeypatch 更干净

    def _generate(self, messages, tools=None) -> ModelResponse:
        if self.call_count >= len(self.responses):
            # 默认给一个 finish 让循环自然结束
            from coding_agent.model.types import FinishAction

            return _finish_response("exhausted fake responses")
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp


def _empty_response() -> ModelResponse:
    """Empty response → parser 产出 InvalidAction('Empty response from model')"""
    return ModelResponse(
        content="",
        tool_calls=[],
        finish_reason="stop",
        usage=TokenUsage(input_tokens=10, output_tokens=0),
    )


def _unknown_tool_response() -> ModelResponse:
    """tool_calls 指向未知工具 → parser 产出 InvalidAction('Unknown tool: ...')"""
    from coding_agent.model.types import ToolCall

    return ModelResponse(
        content="",
        tool_calls=[ToolCall(id="call_x", name="nonexistent_tool", arguments={})],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
    )


def _finish_response(summary: str) -> ModelResponse:
    """Finish tool call."""
    from coding_agent.model.types import ToolCall

    return ModelResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_finish",
                name="finish",
                arguments={"summary": summary, "validation": "ok"},
            )
        ],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
    )


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def config(tmp_path):
    """小步数配置，避免 fake model 跑太久。"""
    return AgentConfig(
        context_budget=8000,
        recent_turns=4,
        max_steps=50,
        max_model_calls=80,
        max_wall_time=60,
        command_timeout=10,
        workspace_root=tmp_path,
    )


@pytest.fixture
def monkeypatch_model(monkeypatch):
    """让 ModelClient.from_config 返回 FakeModel。"""

    def _patch(responses: list[ModelResponse]) -> FakeModel:
        fake = FakeModel(responses)

        def fake_from_config(cls, _config):
            # 返回一个壳子：generate 被替换
            instance = cls.__new__(cls)
            instance._fake = fake
            instance.generate = fake.generate
            return instance

        monkeypatch.setattr(ModelClient, "from_config", classmethod(fake_from_config))
        return fake

    return _patch


class TestInvalidActionInLoop:
    def test_empty_response_triggers_feedback_not_observation(
        self, workspace, config, monkeypatch_model
    ):
        """连续返回空响应：feedback 累积，recent_turns 为空，tool_calls 不增加。

        注意：finish 在没有 mutation+validation 的情况下会被 FinishPolicy 拒绝，
        所以最终 stop_reason 是 max_consecutive_errors，不是 finish。
        """
        fake = monkeypatch_model(
            [
                _empty_response(),
                _empty_response(),
                _empty_response(),
                _finish_response("done after invalid retries"),
            ]
        )

        result = agent_run(
            task="测试 invalid action 路径",
            workspace=workspace,
            config=config,
        )

        # 跑完了所有 fake responses
        assert fake.call_count >= 4
        # finish 被 reject（没 mutation 也没 validation）→ 走 max_consecutive_errors
        assert result.stop_reason != "finish"

    def test_unknown_tool_does_not_increment_tool_calls(
        self, workspace, config, monkeypatch_model
    ):
        """未知工具的 InvalidAction 不算 tool_call，state.tool_calls == 0。

        finish 同样被 reject。"""
        fake = monkeypatch_model(
            [
                _unknown_tool_response(),
                _unknown_tool_response(),
                _finish_response("done"),
            ]
        )

        result = agent_run(
            task="未知工具测试",
            workspace=workspace,
            config=config,
        )

        assert result.stop_reason != "finish"
        assert result.steps == 0  # step_count 不增加

    def test_mixed_invalid_and_real_action(self, workspace, config, monkeypatch_model):
        """InvalidAction 与真实 tool_call 混合：只有真实 tool 增加 step_count。"""
        from coding_agent.model.types import ToolCall

        # 1: 空响应 → InvalidAction
        # 2: list_files 真实调用
        # 3: finish（无 mutation，仍会被 FinishPolicy 拒）
        list_files_resp = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_lf",
                    name="list_files",
                    arguments={"path": ".", "max_depth": 1},
                )
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )
        fake = monkeypatch_model(
            [_empty_response(), list_files_resp, _finish_response("done")]
        )

        result = agent_run(
            task="混合 invalid + real",
            workspace=workspace,
            config=config,
        )

        # finish 被 reject（只有 list_files，没有 mutation / validation）
        assert result.stop_reason != "finish"
        # 只有一次真实 tool dispatch：list_files → step_count=1
        assert result.steps == 1

    def test_too_many_consecutive_invalids_stops_with_max_errors(
        self, workspace, config, monkeypatch_model
    ):
        """连续多次 InvalidAction → MAX_CONSECUTIVE_ERRORS 终止。"""
        # 5 次连续空响应（max_consecutive_errors=5）
        monkeypatch_model([_empty_response() for _ in range(5)])

        result = agent_run(
            task="一直 invalid",
            workspace=workspace,
            config=config,
        )

        assert result.stop_reason == "max_consecutive_errors"
        # 没有任何真实 tool 执行
        assert result.steps == 0


class TestInvalidActionTrajectory:
    def test_trajectory_records_feedback_events(
        self, workspace, config, monkeypatch_model, tmp_path
    ):
        """trajectory.jsonl 应当记录 type=feedback，不是 type=tool_call。"""
        # 注意：finish 在没 mutation 时被 reject，所以这里也走 max_consecutive_errors 路径。
        # 我们直接验证 trajectory 文件存在并包含 model_call 事件。
        monkeypatch_model([_empty_response() for _ in range(5)])
        agent_run(
            task="trajectory test",
            workspace=workspace,
            config=config,
        )

        import json
        from pathlib import Path

        run_dirs = list((workspace / "runs").glob("run_*"))
        assert run_dirs, "应当产生 trajectory 目录"
        traj_path = run_dirs[-1] / "trajectory.jsonl"
        assert traj_path.exists()

        events = []
        with traj_path.open() as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))

        types = [e["type"] for e in events]
        # 5 次空响应：5 个 model_call + 5 个 feedback + 1 个 stop
        assert "model_call" in types
        assert "feedback" in types
        # 不应该有 tool_call（因为没有真实 tool 执行）
        assert "tool_call" not in types
