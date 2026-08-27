"""AgentState：显式控制状态。

设计原则：
- Conversation State（messages）由 LLM 通信使用；
- Control State（AgentState）由 Agent Runtime 控制使用。
- 两者分离，状态变更不依赖 messages 重新解析。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class StopReason(str, Enum):
    """循环终止原因。"""

    FINISH = "finish"  # 模型显式 finish
    MAX_STEPS = "max_steps"
    MAX_MODEL_CALLS = "max_model_calls"
    MAX_WALL_TIME = "max_wall_time"
    MAX_CONSECUTIVE_ERRORS = "max_consecutive_errors"
    MAX_CONSECUTIVE_TIMEOUTS = "max_consecutive_timeouts"
    REPEATED_ACTION = "repeated_action"
    STAGNATION = "stagnation"


@dataclass
class AgentState:
    """显式 Agent 控制状态。

    与 messages 解耦：所有需要 O(1) 查询的控制信号都在此。
    """

    original_task: str
    workspace: Path
    task_mode: str = "existing_repository"  # or "greenfield"

    # --- 进度 ---
    status: str = "RUNNING"  # RUNNING / COMPLETED / STOPPED / ERROR
    step_count: int = 0
    model_calls: int = 0
    tool_calls: int = 0

    # --- 派生事实（程序维护，不来自 LLM summary）---
    inspected_files: set[str] = field(default_factory=set)
    modified_files: set[str] = field(default_factory=set)
    recent_validation: str | None = None  # 最近一次 pytest 结果摘要

    # --- Recent Actions（用于 repeated action 检测）---
    recent_actions: list[tuple[str, str]] = field(default_factory=list)
    """元素：(tool_name, normalized_args_hash)"""

    # --- 错误计数 ---
    consecutive_errors: int = 0
    consecutive_timeouts: int = 0

    # --- Working State（程序维护的紧凑状态）---
    current_goal: str = ""
    important_files: set[str] = field(default_factory=set)
    current_findings: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    # --- 时间 ---
    start_time: float = field(default_factory=time.time)

    # --- 终止 ---
    stop_reason: StopReason | None = None
    finish_summary: str | None = None
    finish_validation: str | None = None

    # --- 用量统计 ---
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @classmethod
    def initialize(cls, task: str, workspace: Path, task_mode: str = "existing_repository") -> "AgentState":
        """初始化一个 AgentState。"""
        return cls(
            original_task=task,
            workspace=workspace,
            task_mode=task_mode,
            current_goal=task[:200],  # 初始 goal 截断
        )

    def record_action(self, tool_name: str, args_hash: str) -> None:
        """记录一次 action 用于重复检测。"""
        self.recent_actions.append((tool_name, args_hash))
        # 只保留最近 20 个
        if len(self.recent_actions) > 20:
            self.recent_actions = self.recent_actions[-20:]

    def record_modified(self, path: str) -> None:
        """记录修改过的文件。"""
        self.modified_files.add(path)

    def record_inspected(self, path: str) -> None:
        """记录读过的文件。"""
        self.inspected_files.add(path)

    def add_finding(self, finding: str) -> None:
        """添加当前发现（最多保留 10 条）。"""
        self.current_findings.append(finding)
        if len(self.current_findings) > 10:
            self.current_findings = self.current_findings[-10:]

    def add_open_question(self, q: str) -> None:
        """添加未解决问题（最多 5 条）。"""
        self.open_questions.append(q)
        if len(self.open_questions) > 5:
            self.open_questions = self.open_questions[-5:]

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def is_stagnant(self, lookback: int = 5) -> bool:
        """检测 stagnation：最近 N 步没有 inspected_files / modified_files 变化。

        注意：这里简化用集合大小变化判断；真实实现可以更精细。
        """
        # TODO: 需要 history 跟踪每步状态变化，V1 简化
        return False  # 默认不触发，termination 里会更精确判断

    def mark_finished(self, summary: str, validation: str = "") -> None:
        """标记为完成（finish tool 调用时）。"""
        self.status = "COMPLETED"
        self.finish_summary = summary
        self.finish_validation = validation
        self.stop_reason = StopReason.FINISH

    def mark_stopped(self, reason: StopReason) -> None:
        """标记为保护性终止。"""
        self.status = "STOPPED"
        self.stop_reason = reason