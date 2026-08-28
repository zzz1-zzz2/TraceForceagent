"""ContextManager.record_feedback 测试。

P0-1 修复目标：把 InvalidAction 等"非真实 tool 反馈"从 (assistant, tool) turn 路径剥离，
改注入到独立 feedback 通道，作为 P0 user 消息。

回归：
- record_feedback 注入到 build() 输出的 messages 中
- feedback 不会被 P3/P2 淘汰（P0）
- feedback 不会构造 fake tool_call_id / tool message（关键安全保证）
- empty / whitespace 被忽略
- record_observation 和 record_feedback 是互斥的两条路径
"""

from pathlib import Path

import pytest

from coding_agent.agent.brief import TaskBrief
from coding_agent.agent.state import AgentState
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager


@pytest.fixture
def state(tmp_path):
    return AgentState.initialize(task="写一个 Python 函数计算斐波那契数列", workspace=tmp_path)


@pytest.fixture
def config():
    return AgentConfig(context_budget=1000, recent_turns=4)


@pytest.fixture
def cm(config):
    return ContextManager(config=config)


class TestRecordFeedbackBasic:
    def test_record_feedback_appends_to_internal_deque(self, cm):
        cm.record_feedback("first feedback")
        cm.record_feedback("second feedback")
        # 内部 deque 长度
        assert len(cm._feedback) == 2
        assert list(cm._feedback) == ["first feedback", "second feedback"]

    def test_record_feedback_ignores_empty(self, cm):
        cm.record_feedback("")
        cm.record_feedback("   ")
        cm.record_feedback("\n\t\n")
        assert len(cm._feedback) == 0

    def test_record_feedback_strips_whitespace(self, cm):
        cm.record_feedback("  hello world  \n")
        assert list(cm._feedback) == ["hello world"]


class TestBuildInjectFeedback:
    def test_feedback_appears_in_built_messages(self, cm, state):
        cm.record_feedback("[InvalidAction] Unknown tool: foo")
        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        joined = " ".join(m.get("content", "") for m in messages)
        assert "[InvalidAction] Unknown tool: foo" in joined

    def test_feedback_does_not_construct_fake_tool_message(self, cm, state):
        """关键安全保证：feedback 路径绝不产生 role=tool 或带 tool_calls 的消息。"""
        cm.record_feedback("[InvalidAction] whatever")
        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        for m in messages:
            # role=tool 必须配套 tool_call_id —— feedback 不该有
            assert m.get("role") != "tool", (
                f"feedback 路径产出了 tool message: {m}"
            )
            # assistant 消息中的 tool_calls 字段——feedback 不该有
            assert "tool_calls" not in m, (
                f"feedback 路径产出了带 tool_calls 的消息: {m}"
            )
            # tool_call_id 也不该出现
            assert "tool_call_id" not in m, (
                f"feedback 路径产出了带 tool_call_id 的消息: {m}"
            )

    def test_feedback_is_role_user(self, cm, state):
        cm.record_feedback("please use a valid tool")
        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        feedback_msgs = [
            m for m in messages
            if m.get("content") == "please use a valid tool"
        ]
        assert len(feedback_msgs) == 1
        assert feedback_msgs[0]["role"] == "user"


class TestFeedbackPriority:
    def test_feedback_survives_tiny_budget(self, state):
        """P0 永远保留——budget 较小时 feedback 内容应在（即使 task 被截断）。

        budget=400 远大于 system prompt 但仍很小，能验证 P0 反馈不被裁。
        """
        cfg = AgentConfig(context_budget=400, recent_turns=2)
        cm = ContextManager(config=cfg)
        cm.record_feedback("CRITICAL: must use valid tool")

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        joined = " ".join(m.get("content", "") for m in messages)
        assert "CRITICAL: must use valid tool" in joined

    def test_feedback_not_dropped_under_pressure(self, state):
        """即使塞很多 recent_turns，feedback（来自 InvalidAction）不会被裁。"""
        cfg = AgentConfig(context_budget=300, recent_turns=4)
        cm = ContextManager(config=cfg)

        from coding_agent.model.types import ToolResult

        # 制造一些大 observation 撑爆 budget
        for i in range(15):
            cm.record_observation(
                state,
                type(
                    "act",
                    (),
                    {
                        "action_id": f"id{i}",
                        "tool_name": "read_file",
                        "arguments": {"path": f"f{i}"},
                    },
                )(),
                ToolResult.ok("x" * 400),
            )

        cm.record_feedback("feedback that must survive budget pressure")

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        joined = " ".join(m.get("content", "") for m in messages)
        assert "feedback that must survive budget pressure" in joined


class TestFeedbackVsObservationIsolation:
    def test_feedback_does_not_pollute_recent_turns(self, cm):
        """record_feedback 不应写入 _recent_turns（避免后续出现 fake tool 配对）。"""
        from coding_agent.model.types import ToolResult

        cm.record_feedback("just feedback, no real tool")
        cm.record_observation(
            type("s", (), {})(),
            type("a", (), {"action_id": "real", "tool_name": "read_file", "arguments": {}})(),
            ToolResult.ok("real result"),
        )
        # _recent_turns 应该只有 1 条（来自真实 record_observation）
        assert len(cm._recent_turns) == 1
        assert cm._recent_turns[0].tool_call_id == "real"

    def test_recent_turns_count_independent_of_feedback(self, cm):
        """feedback 计数与 recent_turns 计数独立——各自有各自的限额。"""
        from coding_agent.model.types import ToolResult

        for i in range(20):
            cm.record_feedback(f"fb{i}")
        assert len(cm._feedback) == 10  # deque maxlen=10
        assert len(cm._recent_turns) == 0  # recent_turns 未被污染

        for i in range(20):
            cm.record_observation(
                type("s", (), {})(),
                type(
                    "a",
                    (),
                    {"action_id": f"id{i}", "tool_name": "read_file", "arguments": {}},
                )(),
                ToolResult.ok("ok"),
            )
        # _recent_turns 上限 = recent_turns * 2 = 8
        assert len(cm._recent_turns) == 8


class TestFeedbackQueueOrder:
    def test_multiple_feedbacks_preserve_order(self, cm, state):
        cm.record_feedback("first")
        cm.record_feedback("second")
        cm.record_feedback("third")

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        contents = [m.get("content") for m in messages]
        # feedback 应该按注入顺序出现在 system 之后
        i1 = contents.index("first")
        i2 = contents.index("second")
        i3 = contents.index("third")
        assert i1 < i2 < i3
        # 但都在 system 之后
        sys_idx = next(
            i for i, m in enumerate(messages) if m.get("role") == "system"
        )
        assert i1 > sys_idx
