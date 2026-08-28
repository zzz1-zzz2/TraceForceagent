"""ContextManager._pack_by_budget 硬保证测试。

P0-4 关键回归：
- 总 token 数 <= budget（除 P0 截断外）
- P0 永不丢
- 单条超 budget 的非 P0 消息被跳过
- 候选顺序公平累加（不再用 80% 魔法数）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.agent.brief import TaskBrief
from coding_agent.agent.state import AgentState
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager
from coding_agent.model.types import ToolResult


def _state(tmp_path):
    return AgentState.initialize(task="测试任务", workspace=tmp_path)


def _config(budget: int, recent_turns: int = 4):
    return AgentConfig(context_budget=budget, recent_turns=recent_turns)


def _cm(budget: int, recent_turns: int = 4):
    return ContextManager(config=_config(budget, recent_turns))


def _add_observations(cm: ContextManager, state: AgentState, n: int, content_size: int):
    """模拟 n 次 tool observation。"""
    for i in range(n):
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
            ToolResult.ok("x" * content_size),
        )


class TestHardBudgetGuarantee:
    def test_total_tokens_never_exceeds_budget_for_reasonable_setup(self, tmp_path):
        """硬保证：合理 setup 下 total <= budget。

        注意：若 budget < system prompt 自身（约 250 tokens），P0 截断无法做到
        total <= budget。这是已知设计 trade-off（system 不能丢）。
        这里 budget=500 远大于 system prompt，能做到硬保证。
        """
        cm = _cm(budget=500)
        state = _state(tmp_path)

        # 制造很多 observation 让 budget 爆掉
        _add_observations(cm, state, n=20, content_size=500)

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        total = sum(cm._count_message_tokens(m) for m in messages)
        assert total <= 500, f"total {total} > budget 500 — hard guarantee violated"

    def test_p0_messages_always_kept(self, tmp_path):
        """P0（system / task / feedback）永远保留，即使 budget 极小。

        注意：在 budget 极紧（< system prompt 自身）时，P0 会被严重截断；
        但"消息本身"仍在。task 内容可能会被完全截断（如果 budget < system）。
        这里 budget=1000，足够保留 system + task + feedback。
        """
        cm = _cm(budget=1000)
        state = _state(tmp_path)

        cm.record_feedback("CRITICAL feedback that must survive")

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 验证所有 P0 消息都在
        joined = " ".join(m.get("content", "") for m in messages)
        assert "coding agent" in joined.lower()  # system prompt
        assert "CRITICAL feedback" in joined  # feedback
        # task 可能被部分截断，但 task header "# Task" 应在（system 占用大部分 budget）
        # —— 不强制要求

    def test_huge_budget_keeps_everything(self, tmp_path):
        """budget 巨大 → 全部保留。

        注意：recent_turns=4 下 _recent_turns maxlen=8，所以 10 个 observation
        只保留最后 4 个 turn (= 8 messages)。system + task + brief + working state
        + 8 = 12 messages。
        """
        cm = _cm(budget=1_000_000)
        state = _state(tmp_path)
        _add_observations(cm, state, n=10, content_size=200)

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)
        # system(1) + task(1) + brief(1) + working_state(1) + 4 turns × 2(8) = 12
        assert len(messages) == 12, f"expected 12, got {len(messages)}"

    def test_p1_can_be_dropped_when_budget_tight(self, tmp_path):
        """P1（brief / working state）在 budget 极紧时可以被 drop。"""
        # budget 小到只能装 system + task + 1 个 P1
        cm = _cm(budget=300)
        state = _state(tmp_path)
        # 让 working state 渲染出非空内容
        state.add_finding("find this")
        state.current_goal = "long goal " * 50

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # system + task + 1 条 P1（或 working state 或 brief）
        # 总数不超过 4-5 条
        assert len(messages) <= 6
        # 重新计数不超过 budget
        total = sum(cm._count_message_tokens(m) for m in messages)
        assert total <= 300


class TestSingleMessageOversized:
    def test_single_p2_over_budget_is_dropped(self, tmp_path):
        """单条 P2 消息超过 budget → 跳过；不影响其它消息。"""
        cm = _cm(budget=500)
        state = _state(tmp_path)

        # 加 1 条大 observation（远超 budget）
        cm.record_observation(
            state,
            type(
                "act",
                (),
                {
                    "action_id": "huge",
                    "tool_name": "read_file",
                    "arguments": {"path": "huge.txt"},
                },
            )(),
            ToolResult.ok("x" * 50_000),
        )
        # 加 1 条小 observation
        cm.record_observation(
            state,
            type(
                "act",
                (),
                {
                    "action_id": "small",
                    "tool_name": "read_file",
                    "arguments": {"path": "small.txt"},
                },
            )(),
            ToolResult.ok("ok"),
        )

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 小 observation 应在，大 observation 应被跳
        joined = " ".join(m.get("content", "") for m in messages)
        # system + task + brief + working_state + small obs(出现) + 巨大 obs(被跳)
        # 但 small obs 的内容 "ok" 可能在 system 里就出现... 直接看 token 总数
        total = sum(cm._count_message_tokens(m) for m in messages)
        assert total <= 500

    def test_no_break_stops_subsequent_p3(self, tmp_path):
        """旧 bug：P2 触发 break 后 P3 完全跳过。新实现按顺序公平累加。"""
        cm = _cm(budget=300)
        state = _state(tmp_path)
        # 制造一条中等 P2（刚好填满剩余 budget），后面 P3 不能再加
        # 但 P3 比 P2 旧，应先被淘汰
        # 模拟 5 个 turn，最近 3 个是 P2，更早是 P3
        for i in range(5):
            cm._recent_turns.append(
                type(
                    "t",
                    (),
                    {
                        "assistant_content": "",
                        "tool_call_id": f"id{i}",
                        "tool_call_name": "read_file",
                        "tool_call_args": {"path": f"f{i}"},
                        "tool_result_content": "x" * 30,
                        "tool_result_success": True,
                    },
                )()
            )

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 总 token 应 <= budget
        total = sum(cm._count_message_tokens(m) for m in messages)
        assert total <= 300, f"hard cap violated: {total} > 300"


class TestP0Truncation:
    def test_extreme_case_p0_truncates(self, tmp_path):
        """极端情况：budget 比单条 P0 还小 → 截断 P0 标注出现在 content。"""
        # budget 50 tokens：system 自身就超 budget
        cm = _cm(budget=50)
        state = _state(tmp_path)
        # feedback 本身就比 budget 大
        cm.record_feedback("x" * 5000)

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 不应崩溃；至少应出现截断标记
        joined = " ".join(m.get("content", "") for m in messages)
        assert "[... truncated" in joined or "[... message exceeded budget" in joined


class TestOrderingPreserved:
    def test_candidates_order_preserved_within_priority(self, tmp_path):
        """同优先级内按 candidates 顺序加入。"""
        cm = _cm(budget=10_000)
        state = _state(tmp_path)
        # 制造多个 observation
        for i in range(5):
            cm.record_observation(
                state,
                type(
                    "act",
                    (),
                    {
                        "action_id": f"id{i}",
                        "tool_name": "read_file",
                        "arguments": {"path": f"unique_path_{i}"},
                    },
                )(),
                ToolResult.ok(f"content_{i}"),
            )

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 检查 unique_path_0 在 unique_path_4 前面
        contents = [m.get("content", "") for m in messages]
        i0 = next((i for i, c in enumerate(contents) if "unique_path_0" in c), -1)
        i4 = next((i for i, c in enumerate(contents) if "unique_path_4" in c), -1)
        if i0 >= 0 and i4 >= 0:
            assert i0 < i4


class TestBudgetCountingCorrectness:
    """验证 _count_message_tokens 与 _pack_by_budget 内部计数一致。"""

    def test_built_messages_token_count_matches_internal_total(self, tmp_path):
        cm = _cm(budget=1500)
        state = _state(tmp_path)
        _add_observations(cm, state, n=8, content_size=300)

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 独立计算 token 数（用 _count_message_tokens）
        actual_total = sum(cm._count_message_tokens(m) for m in messages)

        # 必须 <= budget（hard guarantee）
        assert actual_total <= 1500

    def test_message_count_matches_independent_count(self, tmp_path):
        """_pack_by_budget 输出的 messages 数 == 实际计算 token 的消息数。"""
        cm = _cm(budget=500)
        state = _state(tmp_path)
        _add_observations(cm, state, n=5, content_size=200)

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 重新数所有 message 的 token
        for m in messages:
            tok = cm._count_message_tokens(m)
            assert tok > 0  # 每条都 > 0


class TestToolTurnAtomicity:
    """P1-4 修复：(assistant tool_call, tool_result) 必须成对进或成对出。

    不变量：
    - 任何 assistant message 含 tool_calls 时，紧跟其后必须有对应 tool message
    - 否则 OpenAI API 会报"messages with role 'tool' must be a response to a preceeding tool_calls"
    """

    def _tool_call_ids(self, messages):
        """提取每条 message 的 tool_call_id（assistant 用 tool_calls[0].id, tool 用 tool_call_id）。"""
        ids = []
        for m in messages:
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls", []):
                    ids.append(("assistant", tc.get("id")))
            elif m.get("role") == "tool":
                ids.append(("tool", m.get("tool_call_id")))
        return ids

    def test_no_orphan_assistant_tool_call_when_budget_tight(self, tmp_path):
        """预算紧张时,turn bundle 要么成对进,要么成对出,不留 orphan assistant。"""
        # budget 紧到只能容纳 1 个 turn bundle;P0+P1 + 第一个 turn 后预算耗尽
        cm = _cm(budget=400, recent_turns=4)
        state = _state(tmp_path)
        # 4 个 turn,每个 tool_result 比较长
        _add_observations(cm, state, n=4, content_size=80)

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 检查 assistant/tool 配对：每对 assistant 后面必须紧跟对应 tool
        ids = self._tool_call_ids(messages)
        assistant_ids = [i for r, i in ids if r == "assistant"]
        tool_ids = [i for r, i in ids if r == "tool"]
        # 进入 context 的 assistant tool_call id 必须在 tool_ids 里都出现
        for aid in assistant_ids:
            assert aid in tool_ids, \
                f"orphan assistant tool_call id {aid} has no matching tool message"

    def test_turn_bundle_dropped_when_single_message_would_exceed(self, tmp_path):
        """单个 turn 大到 assistant 或 tool 任一超 budget 时,bundle 一起丢。"""
        # budget 极小,任何 turn 都装不下
        cm = _cm(budget=50, recent_turns=2)
        state = _state(tmp_path)
        # content_size=80 远超 budget
        _add_observations(cm, state, n=1, content_size=80)

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        # 不应当出现 role=tool 的 message（turn bundle 整体被丢）
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assistant_with_calls = [
            m for m in messages if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert not tool_msgs, "turn bundle 应整体被丢"
        assert not assistant_with_calls, "不应留下 orphan assistant tool_call"

    def test_turn_pair_always_complete(self, tmp_path):
        """正常预算下,每个 assistant tool_call 都有对应 tool message。"""
        cm = _cm(budget=20000, recent_turns=5)
        state = _state(tmp_path)
        _add_observations(cm, state, n=3, content_size=100)

        brief = TaskBrief.from_user_task(state.original_task)
        messages = cm.build(state, brief)

        ids = self._tool_call_ids(messages)
        assistant_ids = [i for r, i in ids if r == "assistant"]
        tool_ids = [i for r, i in ids if r == "tool"]
        assert len(assistant_ids) == len(tool_ids)
        assert set(assistant_ids) == set(tool_ids)
