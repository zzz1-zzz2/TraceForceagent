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