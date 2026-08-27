"""Failure-Aware Context Refresh。

测试失败时，把 300 行 traceback 整理成 ~5 行的紧凑 Snapshot，
替换原始 Observation 以避免污染 Active Context。

设计原则：
- 不改变 AgentLoop
- 关闭后 Core Agent 完全不受影响
- 不实现完整 ReCAP（仅做最轻量的"失败后整理"）
"""

from __future__ import annotations

import re

from coding_agent.agent.state import AgentState
from coding_agent.model.types import ToolResult


class FailureAwareRefresher:
    """检测测试失败并构造 Failure Snapshot。"""

    # pytest 失败格式：
    # FAILED tests/test_x.py::test_y - AssertionError: expected ...
    PYTEST_FAILED_RE = re.compile(
        r"^FAILED\s+([\w/_.]+\.py::[\w]+)\s*[-:]\s*(.+)$",
        re.MULTILINE,
    )

    # pytest assertion
    PYTEST_ASSERTION_RE = re.compile(
        r"AssertionError[:\s]+(.+?)(?:\n|$)",
        re.MULTILINE,
    )

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def maybe_refresh(
        self,
        state: AgentState,
        observation: ToolResult,
    ) -> ToolResult:
        """如果 observation 是测试失败，构造 Failure Snapshot。

        Returns:
            - 原始 observation（如果不是测试失败）
            - 紧凑 Failure Snapshot（如果是）
        """
        if not self.enabled:
            return observation

        if not observation.is_validation_failure:
            return observation

        # 是测试失败
        snapshot = self._build_snapshot(state, observation)
        return ToolResult(
            success=False,
            content=snapshot,
            error=observation.error,
            summary=f"FAIL: {snapshot.splitlines()[0]}",
            is_validation_failure=True,
        )

    def _build_snapshot(self, state: AgentState, observation: ToolResult) -> str:
        """构造 ~5 行的 Failure Snapshot。"""
        content = observation.content

        # 抽取失败 test 名
        failed_match = self.PYTEST_FAILED_RE.search(content)
        failed_test = failed_match.group(1) if failed_match else "(unknown)"

        # 抽取 assertion message
        assertion_match = self.PYTEST_ASSERTION_RE.search(content)
        error_msg = assertion_match.group(1).strip()[:200] if assertion_match else "(no assertion msg)"

        # 当前 patch
        modified = sorted(state.modified_files)
        modified_str = ", ".join(modified[:5]) if modified else "(none yet)"

        snapshot_lines = [
            f"❌ FAILED: {failed_test}",
            f"Error: {error_msg}",
            f"Modified files: {modified_str}",
        ]

        # 加入最新发现
        if state.current_findings:
            last_finding = state.current_findings[-1]
            snapshot_lines.append(f"Latest finding: {last_finding}")

        snapshot_lines.append(
            "(Full test log was suppressed. Run `pytest <path>` to see details.)"
        )

        # 更新 Working State
        state.add_finding(f"Test failure in {failed_test}: {error_msg[:100]}")

        return "\n".join(snapshot_lines)