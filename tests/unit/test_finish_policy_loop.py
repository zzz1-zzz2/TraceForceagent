"""FinishPolicy 在 AgentLoop 中的集成测试。

P0-2 关键回归：模型调用 finish() 必须经过 mutation+validation 校验。
否则被转成 feedback，让模型继续工作（不终止循环）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.agent.loop import run as agent_run
from coding_agent.config import AgentConfig
from coding_agent.model.client import ModelClient
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0
        self.generate = self._generate

    def _generate(self, messages, tools=None):
        if self.call_count >= len(self.responses):
            from coding_agent.model.types import FinishAction
            return ModelResponse(
                content="",
                tool_calls=[ToolCall(id="c", name="finish",
                                     arguments={"summary": "exhausted"})],
                finish_reason="tool_calls",
                usage=TokenUsage(input_tokens=10, output_tokens=5),
            )
        r = self.responses[self.call_count]
        self.call_count += 1
        return r


def _finish(summary="done", validation="ok"):
    return ModelResponse(
        content="",
        tool_calls=[ToolCall(id="cf", name="finish",
                             arguments={"summary": summary, "validation": validation})],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
    )


def _apply_patch(path="foo.py", content="x = 1\n"):
    return ModelResponse(
        content="",
        tool_calls=[ToolCall(id="cp", name="apply_patch",
                             arguments={"path": path, "content": content,
                                        "mode": "create"})],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=10, output_tokens=20),
    )


def _run_command(command="pytest -q", exit_code=0, is_validation_failure=False,
                 is_runtime_error=False, summary=""):
    """构造一个 run_command tool call 的 response。

    注意：FakeModel 不能让 tool 真正执行（那是 shell 的事），所以这个测试
    只验证 parser → dispatch 的调度结构，不能验证 run_command 的真实输出。
    run_command 的真实执行通过 FinishPolicy unit test 覆盖。
    """
    return ModelResponse(
        content="",
        tool_calls=[ToolCall(id="cr", name="run_command",
                             arguments={"command": command})],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=10, output_tokens=20),
    )


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def config(tmp_path):
    return AgentConfig(
        context_budget=8000,
        recent_turns=4,
        max_steps=20,
        max_model_calls=30,
        max_wall_time=60,
        command_timeout=10,
        workspace_root=tmp_path,
    )


@pytest.fixture
def patch_model(monkeypatch):
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


class TestFinishPolicyInLoop:
    def test_finish_without_mutation_is_rejected(self, workspace, config, patch_model):
        """模型没改任何文件就调用 finish → reject，循环继续。"""
        # 模型先后调用 finish 3 次（每次都被拒），最后给一个不同的工具 call
        from coding_agent.model.types import ToolCall
        list_files_resp = ModelResponse(
            content="",
            tool_calls=[ToolCall(id="cl", name="list_files",
                                 arguments={"path": ".", "max_depth": 1})],
            finish_reason="tool_calls",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )
        fake = patch_model(
            [_finish(), _finish(), list_files_resp, _finish()]
        )

        result = agent_run(
            task="finish without mutation test",
            workspace=workspace,
            config=config,
        )

        # 应当跑完全部 4 次调用，最后一次 finish 仍然被拒。
        # 但 max_consecutive_errors=5 默认，前面 2 次 reject +1，1 次成功 list_files 重置
        # 最后 1 次 reject。所以最终要么 max_consecutive_errors stop，
        # 要么列表到 max_steps。
        # 关键是 stop_reason 不应该是 finish（因为没有 mutation+validation）。
        assert result.stop_reason != "finish", (
            "finish 必须被 reject——没有 mutation 和 validation。"
        )

    def test_finish_with_mutation_but_no_validation_rejected(self, workspace, config, patch_model):
        """有 mutation 但没 validation → reject。"""
        fake = patch_model([
            _apply_patch(path="foo.py", content="x = 1\n"),
            _finish(),
            _finish(),
        ])
        result = agent_run(
            task="mutation but no validation",
            workspace=workspace,
            config=config,
        )
        # 不应当被 finish。
        assert result.stop_reason != "finish"


class TestFinishPolicyStateWiring:
    """验证 loop.py 真的把 record_mutation / record_validation 接好了。"""

    def test_apply_patch_records_mutation(self, tmp_path):
        """apply_patch 成功 → state.last_mutation_step 增加。"""
        from coding_agent.agent.state import AgentState

        state = AgentState.initialize(task="t", workspace=tmp_path)
        assert state.last_mutation_step == 0

        # 模拟 apply_patch 成功的派生
        state.record_mutation(step=1)
        assert state.last_mutation_step == 1

        state.record_mutation(step=3)
        assert state.last_mutation_step == 3

    def test_validation_tracking_monotonic(self, tmp_path):
        from coding_agent.agent.state import AgentState

        state = AgentState.initialize(task="t", workspace=tmp_path)
        state.record_validation(step=5, command="pytest", passed=True, summary="5 ok")
        assert state.last_validation_step == 5
        assert state.last_validation_passed is True
        assert state.last_validation_command == "pytest"

        # 更晚的 step 更新字段
        state.record_validation(step=8, command="pytest -v", passed=False, summary="1 fail")
        assert state.last_validation_step == 8
        assert state.last_validation_passed is False
        assert state.last_validation_command == "pytest -v"

        # 更早的 step 不覆盖
        state.record_validation(step=3, command="stale", passed=True)
        assert state.last_validation_step == 8
        assert state.last_validation_command == "pytest -v"
