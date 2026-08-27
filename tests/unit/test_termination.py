"""TerminationController 单元测试。"""

from pathlib import Path

import pytest

from coding_agent.agent.state import AgentState, StopReason
from coding_agent.agent.termination import TerminationConfig, TerminationController


@pytest.fixture
def state(tmp_path):
    return AgentState.initialize(task="t", workspace=tmp_path)


@pytest.fixture
def controller():
    return TerminationController(
        TerminationConfig(
            max_steps=10,
            max_model_calls=20,
            max_wall_time=3600,
            max_consecutive_errors=3,
            max_consecutive_timeouts=2,
            repeated_action_limit=3,
        )
    )


class TestNormalTermination:
    def test_no_stop_at_beginning(self, controller, state):
        should, reason, _ = controller.should_stop(state)
        assert not should
        assert reason is None


class TestMaxSteps:
    def test_max_steps_triggers(self, controller, state):
        state.step_count = 10
        should, reason, _ = controller.should_stop(state)
        assert should
        assert reason == StopReason.MAX_STEPS


class TestMaxModelCalls:
    def test_max_model_calls_triggers(self, controller, state):
        state.model_calls = 20
        should, reason, _ = controller.should_stop(state)
        assert should
        assert reason == StopReason.MAX_MODEL_CALLS


class TestConsecutiveErrors:
    def test_consecutive_errors_triggers(self, controller, state):
        state.consecutive_errors = 3
        should, reason, _ = controller.should_stop(state)
        assert should
        assert reason == StopReason.MAX_CONSECUTIVE_ERRORS


class TestConsecutiveTimeouts:
    def test_consecutive_timeouts_triggers(self, controller, state):
        state.consecutive_timeouts = 2
        should, reason, _ = controller.should_stop(state)
        assert should
        assert reason == StopReason.MAX_CONSECUTIVE_TIMEOUTS


class TestRepeatedAction:
    def test_repeated_action_triggers(self, controller, state):
        # 连续 3 次相同动作无新信息
        controller.record_action("read_file", "hash1", observation_changed=False)
        controller.record_action("read_file", "hash1", observation_changed=False)
        controller.record_action("read_file", "hash1", observation_changed=False)
        should, reason, _ = controller.should_stop(state)
        assert should
        assert reason == StopReason.REPEATED_ACTION

    def test_new_info_resets_streak(self, controller, state):
        controller.record_action("read_file", "hash1", observation_changed=False)
        controller.record_action("read_file", "hash1", observation_changed=False)
        controller.record_action("read_file", "hash1", observation_changed=True)
        # 新信息应清空 streaks
        should, reason, _ = controller.should_stop(state)
        assert not should


class TestFeedback:
    def test_repeat_feedback_after_2_same(self, controller):
        controller.record_action("read_file", "h", observation_changed=False)
        controller.record_action("read_file", "h", observation_changed=False)
        feedback = controller.get_repeated_action_feedback()
        assert feedback is not None
        assert "read_file" in feedback

    def test_no_feedback_when_actions_progress(self, controller):
        controller.record_action("a", "h1", observation_changed=False)
        controller.record_action("b", "h2", observation_changed=False)
        feedback = controller.get_repeated_action_feedback()
        assert feedback is None