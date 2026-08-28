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

    # --- Mutation / Validation tracking (P0-2 / P0-3) ---
    # 用于 FinishPolicy 校验：必须"修改 → validation 通过"才能 finish。
    # 0 表示"尚未发生"。
    last_mutation_step: int = 0
    last_validation_step: int = 0
    last_validation_command: str = ""
    last_validation_passed: bool | None = None  # True=pass, False=fail, None=未跑过
    last_validation_summary: str = ""

    # --- 用量统计 ---
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # --- Stagnation 检测 ---
    _state_signature_history: list[tuple] = field(default_factory=list)
    """每步的状态指纹，用于 stagnation 检测。内部字段，不导出。"""

    @classmethod
    def initialize(cls, task: str, workspace: Path, task_mode: str = "existing_repository") -> "AgentState":
        """初始化一个 AgentState。

        task_mode 由调用方决定（通常来自 TaskBrief.from_user_task 的启发式判定），
        本方法不再自行推断，避免多处判定不一致。
        """
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

    def record_mutation(self, step: int) -> None:
        """记录最后一次 mutation 发生的 step（FinishPolicy 用）。

        仅由 apply_patch 成功时调用。
        """
        self.last_mutation_step = max(self.last_mutation_step, step)

    def record_validation(
        self,
        step: int,
        command: str,
        passed: bool,
        summary: str = "",
    ) -> None:
        """记录最后一次 validation（FinishPolicy 用）。

        Args:
            step: 当前 step_count
            command: 执行的命令
            passed: 是否通过
            summary: 简短结果摘要

        语义：
        - 只在 step > last_validation_step 时才更新（更早的事件被忽略）。
        - 这是为了在"validation → mutation → validation"序列里，
          第二次 validation（更新 step）覆盖第一次。
        """
        if step > self.last_validation_step:
            self.last_validation_step = step
            self.last_validation_command = command
            self.last_validation_passed = passed
            self.last_validation_summary = summary

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
        """检测 stagnation：最近 lookback 步 modified_files / inspected_files /
        recent_validation 都没有变化。

        内部维护 _state_signature_history，调用本方法前应至少 lookback 步之后。
        """
        if len(self._state_signature_history) < lookback:
            return False
        recent = self._state_signature_history[-lookback:]
        # 全部相同才算 stagnation（避免误判探索阶段的连续失败）
        return len(set(recent)) == 1

    def mark_step_done(self) -> None:
        """每步结束时调用，记录当前状态指纹。"""
        sig = self._state_signature()
        self._state_signature_history.append(sig)
        # 只保留最近 20 个签名
        if len(self._state_signature_history) > 20:
            self._state_signature_history = self._state_signature_history[-20:]

    def _state_signature(self) -> tuple:
        """构造状态指纹。"""
        return (
            frozenset(self.modified_files),
            frozenset(self.inspected_files),
            self.recent_validation,
            tuple(self.current_findings[-3:]) if self.current_findings else (),
        )

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