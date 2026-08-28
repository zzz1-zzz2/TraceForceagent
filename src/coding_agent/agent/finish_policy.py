"""FinishPolicy：校验 FinishAction 是否可被接受。

背景：模型可能过早调用 finish：
- 没有真正修改任何文件（只是 inspect）
- 修改了文件但没跑 validation
- 跑了 validation 但失败（断言、"test failed" 等）
- 上一次 mutation 之后没再跑过 validation

正确流程：修改 → 跑测试 → 通过 → finish。

本模块暴露两个独立但相关的判断：
1. `classify_validation(observation, command) -> ValidationVerdict`：
   从 run_command 的 ToolResult 判断这次是否是 validation run 及结果。
   通过 RunCommandTool.is_test_command 复用 shell_tool 的判定（单一来源）。

2. `FinishPolicy.check(state, action) -> (accepted, feedback)`：
   校验当前 AgentState 是否满足"可以 finish"的前提。

FinishPolicy 不终止循环；只是 reject finish action 并把反馈注入 context。
终止由 TerminationController / max_steps 负责。
"""

from __future__ import annotations

from dataclasses import dataclass

from coding_agent.agent.state import AgentState
from coding_agent.model.types import FinishAction, ToolResult


@dataclass
class ValidationVerdict:
    """对单次 run_command 调用的分类结果。"""

    is_validation: bool  # 是否看起来是 validation
    passed: bool | None  # 通过/失败/不确定
    reason: str  # 解释为什么是 / 不是 validation


def classify_validation(
    observation: ToolResult,
    command: str,
) -> ValidationVerdict:
    """判断一次 run_command 调用是否构成 validation run。

    判定规则（与 RunCommandTool 内部 _looks_like_test_command 保持一致）：
    - 命令不命中 test 关键字 → 不是 validation
    - runtime error / timeout → 不是 validation（避免误把 timeout 算 fail）
    - 命令命中 test 关键字：
      - exit_code==0 且 not is_validation_failure → passed=True
      - exit_code != 0 或 is_validation_failure → passed=False
    """
    # 延迟导入避免循环依赖（tools 包不依赖 agent）
    from coding_agent.tools.shell import RunCommandTool

    if not RunCommandTool.is_test_command(command):
        return ValidationVerdict(
            is_validation=False,
            passed=None,
            reason=f"command '{command[:60]}' is not a test command",
        )

    # runtime error / timeout → 不是 validation（避免误把 timeout 算 fail）
    if observation.is_runtime_error:
        return ValidationVerdict(
            is_validation=False,
            passed=None,
            reason=f"runtime error: {observation.error[:100] if observation.error else 'unknown'}",
        )

    # 命令看起来是 validation → 判定通过 / 失败
    if observation.is_validation_failure or not observation.success:
        return ValidationVerdict(
            is_validation=True,
            passed=False,
            reason=observation.summary or "validation command failed",
        )
    return ValidationVerdict(
        is_validation=True,
        passed=True,
        reason=observation.summary or "validation command passed",
    )


@dataclass
class FinishPolicy:
    """FinishAction 的接受策略。

    默认拒绝条件（按顺序）：
    1. 从未修改任何文件（last_mutation_step == 0）：
       "No files were modified. Either the task didn't require code changes,
        or you skipped the implementation step."
    2. 修改过文件但从未跑过 validation（last_validation_step == 0）：
       "You modified files but never ran tests. Run your project's test
        suite before calling finish."
    3. 最后一次 mutation 之后没再跑过 validation：
       "You modified files after the last validation. Re-run tests."
    4. 最后一次 validation 失败：
       "Last validation FAILED. Fix the test failures and try again."

    注意：本策略仅适用于代码工程任务。Greenfield 任务（从零创建）也仍然
    至少需要 validation 才能 finish；这是有意为之的"先跑测试再交付"门。
    """

    # 如果为 True，跳过 mutation 检查（用于纯文档/注释任务）
    skip_mutation_check: bool = False

    def check(
        self,
        state: AgentState,
        action: FinishAction,
    ) -> tuple[bool, str | None]:
        """检查 FinishAction 是否可被接受。

        Returns:
            (accepted, feedback)
            - accepted=True: 可以 finish
            - accepted=False: 拒绝，feedback 是给模型的明确指引
        """
        # ---- 1. mutation check ----
        if not self.skip_mutation_check and state.last_mutation_step == 0:
            return False, (
                "No files were modified. If the task requires code changes, "
                "use apply_patch to make them first. If no changes are needed, "
                "explain why in the summary and call finish again."
            )

        # ---- 2. validation 存在性 ----
        if state.last_validation_step == 0:
            return False, (
                "You modified files but never ran the project's test suite. "
                "Use run_command to execute your project's test command "
                "(e.g. `pytest`, `npm test`, `cargo test`) before calling finish."
            )

        # ---- 3. mutation-after-validation ----
        if state.last_mutation_step > state.last_validation_step:
            return False, (
                f"You modified files after the last validation (mutation at "
                f"step {state.last_mutation_step}, last validation at step "
                f"{state.last_validation_step}). Re-run tests before finishing."
            )

        # ---- 4. validation passed ----
        if state.last_validation_passed is False:
            return False, (
                f"Last validation FAILED. "
                f"Command: `{state.last_validation_command}`. "
                f"Summary: {state.last_validation_summary or '(no summary)'}. "
                f"Fix the failures and re-run tests."
            )

        if state.last_validation_passed is None:
            # validation 存在但 passed 状态未知（不应发生，但兜底）
            return False, (
                "Last validation has unknown pass/fail state. Re-run tests."
            )

        # all clear
        return True, None
