"""AgentState 单元测试。"""

from pathlib import Path

import pytest

from coding_agent.agent.state import AgentState, StopReason


class TestAgentState:
    def test_initialize(self, tmp_path):
        state = AgentState.initialize(
            task="修复 bug",
            workspace=tmp_path,
        )
        assert state.original_task == "修复 bug"
        assert state.workspace == tmp_path.resolve()
        assert state.status == "RUNNING"
        assert state.step_count == 0
        assert state.consecutive_errors == 0

    def test_record_modified(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        state.record_modified("src/foo.py")
        state.record_modified("src/bar.py")
        state.record_modified("src/foo.py")  # duplicate
        assert len(state.modified_files) == 2

    def test_record_action_keeps_recent_20(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        for i in range(25):
            state.record_action("read_file", f"hash{i}")
        assert len(state.recent_actions) == 20
        assert state.recent_actions[-1] == ("read_file", "hash24")

    def test_add_finding_caps_at_10(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        for i in range(15):
            state.add_finding(f"finding {i}")
        assert len(state.current_findings) == 10
        assert state.current_findings[-1] == "finding 14"

    def test_mark_finished(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        state.mark_finished("did X", "pytest passed")
        assert state.status == "COMPLETED"
        assert state.finish_summary == "did X"
        assert state.finish_validation == "pytest passed"
        assert state.stop_reason == StopReason.FINISH

    def test_mark_stopped(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        state.mark_stopped(StopReason.MAX_STEPS)
        assert state.status == "STOPPED"
        assert state.stop_reason == StopReason.MAX_STEPS

    def test_total_tokens(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        state.total_input_tokens = 100
        state.total_output_tokens = 50
        assert state.total_tokens() == 150


class TestReadyToFinish:
    """P1-3 修复：validation pass 后应能引导 Agent 调 finish。

    关键不变量：
    - validation passed=True → ready_to_finish=True + 清理 stale 失败痕迹
    - 新 mutation → ready_to_finish=False（强制重跑验证）
    - validation failed → ready_to_finish=False（保留 failure traces）
    """

    def test_passed_validation_sets_ready(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        state.record_validation(step=1, command="pytest", passed=True, summary="3 passed")
        assert state.ready_to_finish is True
        assert state.last_validation_passed is True

    def test_failed_validation_does_not_set_ready(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        state.record_validation(step=1, command="pytest", passed=False, summary="1 failed")
        assert state.ready_to_finish is False
        assert state.last_validation_passed is False

    def test_mutation_clears_ready(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        # 先有验证通过
        state.record_validation(step=1, command="pytest", passed=True)
        assert state.ready_to_finish is True
        # 再有 mutation → ready 必须清空
        state.record_mutation(step=2)
        assert state.ready_to_finish is False

    def test_passed_clears_failure_traces(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        # 模拟之前的失败状态
        state.add_finding("Test failure: assert 1 == 2")
        state.add_open_question("Why did the test fail?")
        state.add_finding("Modified src/foo.py")  # 这个不应被清
        # 验证通过
        state.record_validation(step=1, command="pytest", passed=True)

        # 失败相关痕迹被清,正常 finding 保留
        assert not any("test failure" in f.lower() for f in state.current_findings)
        assert not any("why did" in q.lower() for q in state.open_questions)
        assert any("modified" in f.lower() for f in state.current_findings)

    def test_failed_keeps_failure_traces(self, tmp_path):
        state = AgentState.initialize(task="x", workspace=tmp_path)
        state.add_finding("Test failure: assert 1 == 2")
        state.add_open_question("Why did the test fail?")

        state.record_validation(step=1, command="pytest", passed=False)

        # 失败痕迹保留
        assert len(state.current_findings) == 1
        assert len(state.open_questions) == 1
        assert state.ready_to_finish is False

    def test_passed_updates_recent_validation(self, tmp_path):
        """P1-6 修复：recent_validation 必须更新成 pass summary。

        Working State 渲染 'Latest Validation: ...',
        如果 fail 后 pass 不更新,模型看到 stale 'FAIL' 文本和 ready_to_finish
        hint 自相矛盾。
        """
        state = AgentState.initialize(task="x", workspace=tmp_path)
        state.recent_validation = "FAIL: 1 test failed"
        state.record_validation(step=2, command="pytest", passed=True, summary="3 passed in 0.5s")
        assert state.recent_validation == "3 passed in 0.5s"

    def test_working_state_shows_passed_after_failure(self, tmp_path):
        """端到端验证: fail → pass 后, Working State 不再有 stale 'FAIL'。"""
        from coding_agent.context.working_state import WorkingStateBuilder

        state = AgentState.initialize(task="x", workspace=tmp_path)
        builder = WorkingStateBuilder()

        # 第一次 fail
        state.record_validation(step=1, command="pytest", passed=False,
                                summary="FAIL: 1 test failed")
        text_after_fail = builder.render(state)
        assert "FAIL" in text_after_fail

        # 第二次 pass,更新
        state.record_validation(step=2, command="pytest", passed=True,
                                summary="3 passed in 0.5s")
        text_after_pass = builder.render(state)
        assert "FAIL" not in text_after_pass
        assert "3 passed" in text_after_pass