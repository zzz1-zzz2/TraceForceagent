"""Stagnation 检测 + Working State 自动维护 + TaskMode 单源 测试。"""

from pathlib import Path

import pytest

from coding_agent.agent.brief import TaskBrief, TaskMode
from coding_agent.agent.state import AgentState, StopReason
from coding_agent.agent.termination import TerminationConfig, TerminationController


class TestStagnation:
    def test_no_stagnation_initially(self, tmp_path):
        state = AgentState.initialize(task="t", workspace=tmp_path)
        # mark_step_done 至少要 N 次才可能触发
        for _ in range(3):
            state.mark_step_done()
        assert not state.is_stagnant(lookback=5)

    def test_stagnation_when_state_unchanged(self, tmp_path):
        state = AgentState.initialize(task="t", workspace=tmp_path)
        # 连续 5+ 步状态完全不变
        for _ in range(6):
            state.mark_step_done()
        assert state.is_stagnant(lookback=5)

    def test_no_stagnation_when_state_changes(self, tmp_path):
        state = AgentState.initialize(task="t", workspace=tmp_path)
        for _ in range(4):
            state.mark_step_done()
        state.record_modified("x.py")  # 在第 5 步前修改
        state.mark_step_done()  # 第 5 步 signature 不同
        # history[-5:] 应包含 4 个空 + 1 个有 x.py → 不是全部相同
        assert not state.is_stagnant(lookback=5)

    def test_signature_history_caps_at_20(self, tmp_path):
        state = AgentState.initialize(task="t", workspace=tmp_path)
        for i in range(25):
            state.record_modified(f"file{i}.py")
            state.mark_step_done()
        assert len(state._state_signature_history) == 20


class TestStagnationTriggersTermination:
    def test_stagnation_triggers_stop(self, tmp_path):
        cfg = TerminationConfig(stagnation_limit=5)
        controller = TerminationController(cfg)
        state = AgentState.initialize(task="t", workspace=tmp_path)
        # 5+ 步无变化
        for _ in range(6):
            state.mark_step_done()
        should, reason, _ = controller.should_stop(state)
        assert should
        assert reason == StopReason.STAGNATION


class TestTaskModeConsistency:
    """TaskMode 应来自 TaskBrief，AgentState.initialize 不再自己判定。"""

    def test_strong_creation_intent_in_empty_workspace_yields_greenfield(self, tmp_path):
        brief = TaskBrief.from_user_task("create a CLI tool from scratch", workspace=tmp_path)
        assert brief.task_mode == TaskMode.GREENFIELD

    def test_generic_coding_verbs_do_not_force_greenfield(self, tmp_path):
        for task in ["implement auth", "write helper", "build target"]:
            assert TaskBrief.from_user_task(task, workspace=tmp_path).task_mode == TaskMode.EXISTING_REPOSITORY

    def test_nonempty_workspace_defaults_existing(self, tmp_path):
        (tmp_path / "README.md").write_text("existing\n")
        brief = TaskBrief.from_user_task("create a CLI tool from scratch", workspace=tmp_path)
        assert brief.task_mode == TaskMode.EXISTING_REPOSITORY

    def test_explicit_task_mode_overrides_workspace(self, tmp_path):
        (tmp_path / "README.md").write_text("existing\n")
        brief = TaskBrief.from_user_task(
            "fix auth", task_mode=TaskMode.GREENFIELD, workspace=tmp_path,
        )
        assert brief.task_mode == TaskMode.GREENFIELD

    def test_brief_task_mode_overrides_state_default(self, tmp_path):
        """显式 TaskBrief mode 可覆盖 AgentState 默认值。"""
        state = AgentState.initialize(
            task="fix auth",
            workspace=tmp_path,
            task_mode=TaskMode.EXISTING_REPOSITORY.value,
        )
        brief = TaskBrief.from_user_task(
            "fix auth", task_mode=TaskMode.GREENFIELD, workspace=tmp_path,
        )
        state.task_mode = brief.task_mode.value
        assert state.task_mode == "greenfield"


class TestWorkingStatePopulation:
    """findings 应该由 loop 在关键事件时写入。"""

    def test_modified_records_finding(self, tmp_path):
        state = AgentState.initialize(task="t", workspace=tmp_path)
        # 模拟 loop.py 的 modify 分支
        state.record_modified("src/foo.py")
        state.add_finding(f"Modified src/foo.py")
        assert any("Modified src/foo.py" in f for f in state.current_findings)

    def test_validation_failure_records_finding(self, tmp_path):
        state = AgentState.initialize(task="t", workspace=tmp_path)
        # 模拟 loop.py 的 pytest fail 分支
        state.recent_validation = "test_x failed"
        state.add_finding(f"Test failure: test_x failed")
        state.add_open_question("Why did the test fail?")
        assert any("Test failure" in f for f in state.current_findings)
        assert any("Why" in q for q in state.open_questions)