"""ContextManager 测试：tiktoken 计数 + 优先级淘汰。"""

from pathlib import Path

import pytest

from coding_agent.agent.brief import TaskBrief
from coding_agent.agent.state import AgentState
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager


@pytest.fixture
def state(tmp_path):
    return AgentState.initialize(task="测试任务描述 " * 50, workspace=tmp_path)


@pytest.fixture
def config():
    return AgentConfig(context_budget=1000, recent_turns=4)


@pytest.fixture
def cm(config):
    return ContextManager(config=config)


class TestTokenCounting:
    def test_count_tokens_nonempty(self, cm):
        n = cm._count_tokens("hello world")
        assert n > 0
        assert n < 10  # 短文本 token 数应很少

    def test_count_tokens_chinese(self, cm):
        # cl100k_base 对中文按字符计
        n = cm._count_tokens("你好世界")
        assert n >= 4  # 至少 4 个中文字符

    def test_count_message_tokens(self, cm):
        msg = {"role": "system", "content": "You are a coding agent."}
        n = cm._count_message_tokens(msg)
        assert n > 0


class TestBuild:
    def test_build_returns_messages(self, cm, state):
        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        assert isinstance(messages, list)
        assert len(messages) >= 2  # 至少有 system + user

    def test_system_prompt_always_first(self, cm, state):
        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        assert messages[0]["role"] == "system"

    def test_original_task_included(self, cm, state):
        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        joined = " ".join(m.get("content", "") for m in messages)
        assert state.original_task in joined


class TestPriorityTrimming:
    def test_trimming_under_budget_keeps_all(self, cm, state, config):
        """小 context 时所有 message 都保留。"""
        # 把 budget 调到很大
        cm.config.context_budget = 1_000_000
        brief = TaskBrief.from_user_task(state.original_task)
        # 模拟加一些 turn
        from coding_agent.model.types import ToolResult

        for _ in range(5):
            cm.record_observation(
                state,
                type("act", (), {"action_id": "x", "tool_name": "read_file", "arguments": {"path": "x"}})(),
                ToolResult.ok("content " * 100),
            )
        messages = cm.build(state, brief)
        # 至少有 system + task + brief + working state + 5 turns × 2
        assert len(messages) >= 12

    def test_trimming_over_budget_drops_lower_priority(self):
        """超出 budget 时 P3/P2 被丢弃，P0/P1 保留。"""
        cfg = AgentConfig(context_budget=500, recent_turns=4)
        cm = ContextManager(config=cfg)

        state = AgentState.initialize(task="t " * 200, workspace=Path("/tmp"))

        from coding_agent.model.types import ToolResult

        # 加很多 turn 让 budget 爆掉
        for i in range(20):
            cm.record_observation(
                state,
                type("act", (), {"action_id": f"x{i}", "tool_name": "read_file", "arguments": {"path": f"f{i}"}})(),
                ToolResult.ok("x" * 500),  # 大 observation
            )
        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # System + Task 必须在
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles  # task
        # P0/P1 保留：messages 数量不应过多
        assert len(messages) < 30  # 不是全部 40+ 条