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
from coding_agent.agent.state import AgentState
from coding_agent.agent.termination import TerminationConfig, TerminationController
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager
from coding_agent.model.client import ModelClient
from coding_agent.model.parsers.openai_compatible import OpenAICompatibleParser
from coding_agent.model.types import FinishAction
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


def run(task: str, workspace: Path, config: AgentConfig) -> AgentRunResult:
    """运行 Agent 完成一个编程任务。

    主入口。
    """
    import time
    import uuid

    start = time.time()
    run_id = f"run_{int(start)}_{uuid.uuid4().hex[:6]}"

    # 1. 初始化
    state = AgentState.initialize(
        task=task,
        workspace=workspace,
        task_mode=TaskMode.GREENFIELD.value if "greenfield" in task.lower() else TaskMode.EXISTING_REPOSITORY.value,
    )
    brief = TaskBrief.from_user_task(task)

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
    trajectory = TrajectoryLogger(run_id=run_id, workspace=workspace)

    try:
        # 3. 主循环
        while True:
            should_stop, stop_reason, feedback = termination.should_stop(state)
            if should_stop:
                state.mark_stopped(stop_reason)
                trajectory.record_stop(state, stop_reason.value)
                break

            # 构造 messages
            messages = context_manager.build(state, brief)

            # 如果有重复动作反馈，注入到 messages
            repeat_feedback = termination.get_repeated_action_feedback()
            if repeat_feedback:
                messages.append({
                    "role": "user",
                    "content": f"[System Feedback] {repeat_feedback}",
                })

            # 调用 LLM
            response = model_client.generate(
                messages=messages,
                tools=registry.schemas(),
            )
            state.model_calls += 1
            state.total_input_tokens += response.usage.input_tokens
            state.total_output_tokens += response.usage.output_tokens
            trajectory.record_model_call(state, response)

            # 解析
            action = parser.parse(response)

            if isinstance(action, FinishAction):
                state.mark_finished(action.summary, action.validation)
                trajectory.record_finish(state, action)
                break

            # Dispatch tool
            tool = registry.get(action.tool_name)
            if tool is None:
                observation = tool.unknown_tool_observation(action.tool_name)
                state.consecutive_errors += 1
            else:
                try:
                    observation = tool.execute(action.arguments, runtime)
                    if observation.success:
                        state.consecutive_errors = 0
                    else:
                        state.consecutive_errors += 1
                except Exception as e:
                    observation = tool.exception_observation(e)
                    state.consecutive_errors += 1

            # 记录 + 更新状态
            trajectory.record_tool_call(state, action, observation)
            state.step_count += 1
            state.tool_calls += 1
            state.record_action(action.tool_name, action.args_hash)

            # 派生状态更新
            if action.tool_name in ("apply_patch", "patch"):
                if observation.success and action.arguments.get("path"):
                    state.record_modified(action.arguments["path"])
            elif action.tool_name in ("read_file",):
                if observation.success and action.arguments.get("path"):
                    state.record_inspected(action.arguments["path"])

            if observation.is_validation_failure:
                state.recent_validation = observation.summary

            # 注入 Observation 到 Active Context
            context_manager.record_observation(state, action, observation)

            termination.record_action(
                action.tool_name,
                action.args_hash,
                observation_changed=observation.success,
            )

    finally:
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