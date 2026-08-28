"""AgentLoop：核心控制循环（7 步循环）。

状态转换：
  init → build_messages → model.generate → parser.parse
  → if finish: finalize
  → else dispatch tool → record + update state
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from coding_agent.agent.brief import TaskBrief, TaskMode
from coding_agent.agent.finish_policy import FinishPolicy, classify_validation
from coding_agent.agent.state import AgentState
from coding_agent.agent.termination import TerminationConfig, TerminationController
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager
from coding_agent.emitter import EventEmitter
from coding_agent.events import (
    ModelCompleted,
    ModelStarted,
    RunFinished,
    RunStarted,
    ToolCompleted,
    ToolStarted,
    TurnEnded,
    TurnStarted,
)
from coding_agent.model.client import ModelClient
from coding_agent.model.parsers.openai_compatible import OpenAICompatibleParser
from coding_agent.model.types import FinishAction, ToolResult
from coding_agent.recovery.failure_refresh import FailureAwareRefresher
from coding_agent.tools.registry import default_registry
from coding_agent.trajectory.logger import TrajectoryLogger
from coding_agent.runtime.local import LocalRuntime


@dataclass
class AgentRunResult:
    """一次完整 Agent Run 的最终结果。"""

    summary: str
    validation: str
    stop_reason: str
    steps: int
    total_tokens: int
    duration: float
    trajectory_path: Optional[Path] = None


def run(
    task: str,
    workspace: Path,
    config: AgentConfig,
    emitter: EventEmitter | None = None,
) -> AgentRunResult:
    """运行 Agent 完成一个编程任务。

    主入口。
    """
    import time
    import uuid

    start = time.time()
    run_id = f"run_{int(start)}_{uuid.uuid4().hex[:6]}"
    events = emitter or EventEmitter()

    # 1. 初始化
    state = AgentState.initialize(
        task=task,
        workspace=workspace,
        task_mode=TaskMode.EXISTING_REPOSITORY.value,  # 占位，下一行立刻覆盖
    )
    brief = TaskBrief.from_user_task(task, workspace=workspace)
    # TaskMode 单源：以 brief 的判定为准
    state.task_mode = brief.task_mode.value

    # 2. 注册组件
    runtime = LocalRuntime(workspace=workspace, config=config)
    registry = default_registry()
    model_client = ModelClient.from_config(config)
    parser = OpenAICompatibleParser(registry=registry)
    context_manager = ContextManager(config=config)
    termination = TerminationController(TerminationConfig(
        max_steps=config.max_steps,
        max_model_calls=config.max_model_calls,
        max_wall_time=config.max_wall_time,
    ))
    finish_policy = FinishPolicy()
    failure_refresher = FailureAwareRefresher(enabled=config.enable_failure_refresh)
    trajectory = TrajectoryLogger(
        run_id=run_id,
        workspace=workspace,
        trace_root=config.trace_root,
    )
    events.emit(RunStarted(run_id=run_id, task=task, workspace=str(workspace)))

    try:
        # 3. 主循环
        while True:
            should_stop, stop_reason, feedback = termination.should_stop(state)
            if should_stop:
                state.mark_stopped(stop_reason)
                trajectory.record_stop(state, stop_reason.value)
                break

            # 构造 messages
            turn_number = state.step_count + 1
            events.emit(TurnStarted(run_id=run_id, turn=turn_number))
            messages = context_manager.build(state, brief)

            # 如果有重复动作反馈，注入到 messages
            repeat_feedback = termination.get_repeated_action_feedback()
            if repeat_feedback:
                messages.append({
                    "role": "user",
                    "content": f"[System Feedback] {repeat_feedback}",
                })

            # 调用 LLM
            events.emit(ModelStarted(
                run_id=run_id,
                turn=turn_number,
                model=getattr(model_client, "model", ""),
            ))
            response = model_client.generate(
                messages=messages,
                tools=registry.schemas(),
            )
            state.model_calls += 1
            state.total_input_tokens += response.usage.input_tokens
            state.total_output_tokens += response.usage.output_tokens
            trajectory.record_model_call(state, response)
            events.emit(ModelCompleted(
                run_id=run_id,
                turn=turn_number,
                model=getattr(model_client, "model", ""),
                response=response,
            ))

            # 解析
            action = parser.parse(response)

            if isinstance(action, FinishAction):
                # FinishPolicy 校验：只有"修改过 + 验证通过"才接受 finish。
                # 否则转换为 feedback，让模型继续工作。
                accepted, feedback = finish_policy.check(state, action)
                if not accepted:
                    fb_text = f"[FinishPolicy] {feedback}"
                    context_manager.record_feedback(fb_text)
                    state.consecutive_errors += 1
                    trajectory.record_feedback(state, fb_text)
                    state.mark_step_done()
                    events.emit(TurnEnded(
                        run_id=run_id,
                        turn=turn_number,
                        status="finish_rejected",
                    ))
                    continue
                state.mark_finished(
                    action.summary,
                    action.validation,
                    action.validation_skipped_reason,
                )
                trajectory.record_finish(state, action)
                events.emit(TurnEnded(run_id=run_id, turn=turn_number, status="finished"))
                break

            # 1) InvalidAction：解析器已捕获错误（empty response / unknown tool / invalid args）
            # 关键修复：不构造 fake tool message，而是注入高优先级 user feedback
            if action.is_invalid:
                tool_list = ", ".join(registry.names())
                feedback = (
                    f"[InvalidAction] {action.error_msg}\n"
                    f"Available tools: {tool_list}.\n"
                    f"You MUST respond with a valid tool call in your next message. "
                    f"Do not output plain text without a tool call."
                )
                context_manager.record_feedback(feedback)
                state.consecutive_errors += 1
                # 审计日志：记录 feedback 事件（不算 tool_call）
                trajectory.record_feedback(state, feedback)
                # 注意：feedback 不算真实 step，所以不递增 step_count / tool_calls。
                # 但 mark_step_done 仍需调用以保证 stagnation signature 推进。
                state.mark_step_done()
                # 不走下面的 dispatch / state 派生 / termination.record_action
                events.emit(TurnEnded(run_id=run_id, turn=turn_number, status="invalid"))
                continue

            # 2) ToolAction：dispatch 到 Tool
            events.emit(ToolStarted(
                run_id=run_id,
                turn=turn_number,
                tool_name=action.tool_name,
                action_id=action.action_id,
                arguments=action.arguments,
            ))
            tool = registry.get(action.tool_name)
            if tool is None:
                # 未知 tool 优雅降级，告诉模型有哪些可用 tool
                observation = ToolResult.fail(
                    f"Unknown tool: '{action.tool_name}'. "
                    f"Available tools: {', '.join(registry.names())}",
                    is_runtime_error=True,
                )
                state.consecutive_errors += 1
            else:
                try:
                    observation = tool.execute(action.arguments, runtime)
                    # FailureAwareRefresher: 测试失败时把几百行 traceback
                    # 压缩成 ~5 行 snapshot，减少 Active Context 占用。
                    observation = failure_refresher.maybe_refresh(state, observation)
                    if observation.success:
                        state.consecutive_errors = 0
                    else:
                        state.consecutive_errors += 1
                    # timeout 单独计数
                    if observation.is_timeout:
                        state.consecutive_timeouts += 1
                    else:
                        state.consecutive_timeouts = 0
                except Exception as e:
                    observation = tool.exception_observation(e)
                    state.consecutive_errors += 1

            # 记录 + 更新状态
            trajectory.record_tool_call(state, action, observation)
            events.emit(ToolCompleted(
                run_id=run_id,
                turn=turn_number,
                tool_name=action.tool_name,
                action_id=action.action_id,
                result=observation,
            ))
            state.step_count += 1
            state.tool_calls += 1
            state.record_action(action.tool_name, action.args_hash)

            # 派生状态更新（基于 tool_name 分类）
            if action.tool_name in ("apply_patch", "patch"):
                if observation.success and action.arguments.get("path"):
                    state.record_modified(action.arguments["path"])
                    state.add_finding(f"Modified {action.arguments['path']}")
                    # 记录 mutation 发生位置（FinishPolicy 用）
                    state.record_mutation(state.step_count)
            elif action.tool_name == "read_file":
                if observation.success and action.arguments.get("path"):
                    state.record_inspected(action.arguments["path"])
            elif action.tool_name == "search_code":
                if observation.success:
                    # 抽取匹配数
                    import re as _re

                    m = _re.search(r"Found (\d+) matches", observation.content)
                    if m:
                        state.add_finding(
                            f"search_code('{action.arguments.get('query', '')}') → {m.group(1)} matches"
                        )
            elif action.tool_name == "run_command":
                # 命令是测试且失败 → 记录
                if observation.is_validation_failure:
                    state.recent_validation = observation.summary or "test failed"
                    state.add_finding(
                        f"Test failure: {observation.summary or 'see logs'}"
                    )
                    state.add_open_question(
                        "Why did the test fail? Inspect modified files and recent test output."
                    )
                # 识别 validation run 并记录到 state（无论 pass/fail）
                cmd = action.arguments.get("command", "")
                verdict = classify_validation(observation, cmd)
                if verdict.is_validation:
                    state.record_validation(
                        step=state.step_count,
                        command=cmd,
                        passed=bool(verdict.passed),
                        summary=verdict.reason,
                    )

            if observation.is_validation_failure:
                state.recent_validation = observation.summary

            # 注入 Observation 到 Active Context
            context_manager.record_observation(state, action, observation)

            termination.record_action(
                action.tool_name,
                action.args_hash,
                observation_changed=observation.success,
            )

            # 记录 step 状态指纹（stagnation 检测用）
            state.mark_step_done()
            events.emit(TurnEnded(run_id=run_id, turn=turn_number, status="completed"))

    finally:
        events.emit(RunFinished(
            run_id=run_id,
            status=state.status,
            reason=state.stop_reason.value if state.stop_reason else "unknown",
        ))
        trajectory.close()

    return AgentRunResult(
        summary=state.finish_summary or "(no summary)",
        validation=state.finish_validation or "",
        stop_reason=state.stop_reason.value if state.stop_reason else "unknown",
        steps=state.step_count,
        total_tokens=state.total_tokens(),
        duration=time.time() - start,
        trajectory_path=trajectory.path,
    )