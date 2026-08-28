"""FinishPolicy 单元测试。

P0-2 关键回归：finish action 必须经过 mutation+validation 校验，否则被 reject。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.agent.finish_policy import FinishPolicy, classify_validation
from coding_agent.agent.state import AgentState
from coding_agent.model.types import FinishAction, ToolResult


class TestClassifyValidation:
    """classify_validation 是 finish_policy 的辅助判定。"""

    def test_pytest_passing_is_validation_pass(self):
        obs = ToolResult.ok("===== 5 passed =====", summary="pytest OK")
        v = classify_validation(obs, "pytest -q")
        assert v.is_validation is True
        assert v.passed is True

    def test_pytest_failing_is_validation_fail(self):
        obs = ToolResult.fail(
            "===== 1 failed =====", is_validation_failure=True,
            summary="pytest failed",
        )
        v = classify_validation(obs, "pytest -q")
        assert v.is_validation is True
        assert v.passed is False

    def test_npm_test_pass(self):
        obs = ToolResult.ok("Tests: 5 passed, 5 total", summary="npm test OK")
        v = classify_validation(obs, "npm test")
        assert v.is_validation is True
        assert v.passed is True

    def test_ls_is_not_validation(self):
        obs = ToolResult.ok("file1\nfile2", summary="ls OK")
        v = classify_validation(obs, "ls -la")
        assert v.is_validation is False
        assert v.passed is None

    def test_echo_is_not_validation(self):
        obs = ToolResult.ok("hello", summary="echo")
        v = classify_validation(obs, "echo hello")
        assert v.is_validation is False
        assert v.passed is None

    def test_timeout_is_not_validation_fail(self):
        """timeout 不算 validation fail——避免模型因卡死的测试被误拒 finish。"""
        obs = ToolResult.fail(
            "Timeout after 60s",
            is_runtime_error=True,
            is_timeout=True,
        )
        v = classify_validation(obs, "pytest -q")
        assert v.is_validation is False
        assert v.passed is None

    def test_executable_not_found_is_not_validation(self):
        obs = ToolResult.fail(
            "pytest: command not found",
            is_runtime_error=True,
        )
        v = classify_validation(obs, "pytest -q")
        assert v.is_validation is False
        assert v.passed is None


class TestFinishPolicyMutationCheck:
    def test_finish_without_mutation_rejected(self):
        """没改任何文件 → reject"""
        state = AgentState.initialize(task="t", workspace=Path("/tmp"))
        action = FinishAction(summary="done", validation="ok")
        policy = FinishPolicy()
        accepted, feedback = policy.check(state, action)
        assert accepted is False
        assert "No files were modified" in feedback

    def test_finish_with_mutation_but_no_validation_rejected(self):
        state = AgentState.initialize(task="t", workspace=Path("/tmp"))
        state.record_mutation(step=1)
        action = FinishAction(summary="done", validation="ok")
        policy = FinishPolicy()
        accepted, feedback = policy.check(state, action)
        assert accepted is False
        assert "never ran" in feedback.lower() or "test suite" in feedback.lower()

    def test_finish_with_validation_failure_rejected(self):
        state = AgentState.initialize(task="t", workspace=Path("/tmp"))
        state.record_mutation(step=1)
        state.record_validation(step=2, command="pytest -q", passed=False, summary="1 failed")
        action = FinishAction(summary="done", validation="ok")
        policy = FinishPolicy()
        accepted, feedback = policy.check(state, action)
        assert accepted is False
        assert "FAILED" in feedback
        assert "pytest -q" in feedback

    def test_finish_with_mutation_after_validation_rejected(self):
        """mutation → validation pass → mutation → 没再 validation → reject"""
        state = AgentState.initialize(task="t", workspace=Path("/tmp"))
        state.record_mutation(step=1)
        state.record_validation(step=2, command="pytest -q", passed=True)
        state.record_mutation(step=3)  # 又改了一次
        action = FinishAction(summary="done", validation="ok")
        policy = FinishPolicy()
        accepted, feedback = policy.check(state, action)
        assert accepted is False
        assert "after the last validation" in feedback

    def test_finish_with_mutation_and_validation_passed_accepted(self):
        state = AgentState.initialize(task="t", workspace=Path("/tmp"))
        state.record_mutation(step=1)
        state.record_validation(step=2, command="pytest -q", passed=True, summary="5 passed")
        action = FinishAction(summary="done", validation="ok")
        policy = FinishPolicy()
        accepted, feedback = policy.check(state, action)
        assert accepted is True
        assert feedback is None

    def test_skip_mutation_check_allows_finish_without_mutation(self):
        """纯文档 / 注释任务可跳过 mutation 校验。"""
        state = AgentState.initialize(task="t", workspace=Path("/tmp"))
        state.record_validation(step=1, command="pytest -q", passed=True)
        action = FinishAction(summary="docs only", validation="ok")
        policy = FinishPolicy(skip_mutation_check=True)
        accepted, feedback = policy.check(state, action)
        assert accepted is True


class TestFinishPolicyStepOrdering:
    """确保 record_mutation / record_validation 的 step 比较正确。"""

    def test_record_validation_with_later_step_overrides(self):
        state = AgentState.initialize(task="t", workspace=Path("/tmp"))
        state.record_mutation(step=1)
        state.record_validation(step=2, command="pytest", passed=False, summary="x")
        # 后续又跑了一次 pass validation
        state.record_validation(step=3, command="pytest", passed=True, summary="ok")
        # 现在 last_validation_step=3 > last_mutation_step=1
        action = FinishAction(summary="done", validation="ok")
        policy = FinishPolicy()
        accepted, _ = policy.check(state, action)
        assert accepted is True

    def test_record_validation_with_earlier_step_ignored(self):
        """如果传入更早的 step，max() 保证不被覆盖。"""
        state = AgentState.initialize(task="t", workspace=Path("/tmp"))
        state.record_mutation(step=5)
        state.record_validation(step=10, command="pytest", passed=True)
        # 用更小的 step 调用
        state.record_validation(step=3, command="old-pytest", passed=False)
        # 仍以 step=10 为准
        assert state.last_validation_step == 10
        assert state.last_validation_passed is True
        assert state.last_validation_command == "pytest"
