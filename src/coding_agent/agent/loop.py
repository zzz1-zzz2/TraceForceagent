"""AgentLoop：核心控制循环与兼容 runner。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from coding_agent.agent.brief import TaskBrief, TaskMode
from coding_agent.agent.finish_policy import FinishPolicy, classify_validation
from coding_agent.agent.state import AgentState
from coding_agent.agent.termination import TerminationConfig, TerminationController
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager
from coding_agent.emitter import EventEmitter
from coding_agent.events import (
    FeedbackRecorded,
    FinishAccepted,
    ModelCompleted,
    ModelFailed,
    ModelResponseSnapshot,
    ModelStarted,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
    ToolCompleted,
    ToolFailed,
    ToolResultSnapshot,
    ToolStarted,
    TurnEnded,
    TurnStarted,
    ValidationCompleted,
)
from coding_agent.model.client import ModelClient
from coding_agent.model.parsers.openai_compatible import OpenAICompatibleParser
from coding_agent.model.types import AgentAction, FinishAction, ToolResult
from coding_agent.recovery.failure_refresh import FailureAwareRefresher
from coding_agent.runtime.local import LocalRuntime
from coding_agent.tools.registry import default_registry
from coding_agent.trajectory import TrajectoryEventSink, TrajectoryLogger


@dataclass
class AgentRunResult:
    """一次完整 Agent Run 的最终结果。"""

    summary: str
    validation: str
    stop_reason: str
    steps: int
    total_tokens: int
    duration: float
    trajectory_path: Path | None = None


def _snapshot(state: AgentState, *, reason: str = "") -> RunStateSnapshot:
    """Build an immutable terminal view without exposing AgentState containers."""
    return RunStateSnapshot(
        status=state.status,
        reason=reason or (state.stop_reason.value if state.stop_reason else ""),
        summary=state.finish_summary or "",
        validation=state.finish_validation or "",
        validation_skipped_reason=state.finish_validation_skipped_reason or "",
        steps=state.step_count,
        total_tokens=state.total_tokens(),
        modified_files=tuple(sorted(state.modified_files)),
    )


def run(
    task: str,
    workspace: Path,
    config: AgentConfig,
    emitter: EventEmitter | None = None,
    task_mode: TaskMode | str | None = None,
    trajectory_sink: TrajectoryEventSink | None = None,
) -> AgentRunResult:
    """Run the event-only loop and assemble the default trajectory subscriber.

    The loop itself never creates, writes, or closes a ``TrajectoryLogger``.
    Injected sinks are observed but not owned by this compatibility wrapper.
    """
    events = emitter or EventEmitter()
    owns_sink = trajectory_sink is None
    run_id = f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    if trajectory_sink is None:
        logger = TrajectoryLogger(run_id=run_id, workspace=workspace, trace_root=config.trace_root)
        trajectory_sink = TrajectoryEventSink(logger)
    else:
        run_id = getattr(getattr(trajectory_sink, "logger", None), "run_id", run_id)
    events.subscribe(trajectory_sink, critical=True, prepend=True)
    trajectory_path = trajectory_sink.path
    try:
        return _run_loop(
            task=task,
            workspace=workspace,
            config=config,
            events=events,
            task_mode=task_mode,
            trajectory_path=trajectory_path,
            run_id=run_id,
        )
    finally:
        if owns_sink:
            events.unsubscribe(trajectory_sink)
            trajectory_sink.close()


def _run_loop(
    task: str,
    workspace: Path,
    config: AgentConfig,
    events: EventEmitter,
    task_mode: TaskMode | str | None = None,
    trajectory_path: Path | None = None,
    run_id: str | None = None,
) -> AgentRunResult:
    """Execute the AgentLoop; all observability is emitted as typed events."""
    start = time.time()
    run_id = run_id or f"run_{int(start)}_{uuid.uuid4().hex[:6]}"
    turn_number = 0
    active_turn: int | None = None
    active_model = False
    active_tool: tuple[AgentAction, ToolResult | None, int] | None = None

    state = AgentState.initialize(
        task=task,
        workspace=workspace,
        task_mode=TaskMode.EXISTING_REPOSITORY.value,
    )
    brief = TaskBrief.from_user_task(task, task_mode=task_mode, workspace=workspace)
    state.task_mode = brief.task_mode.value

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

    def end_turn(turn: int, status: str) -> None:
        nonlocal active_turn
        events.emit(TurnEnded(run_id=run_id, turn=turn, status=status))
        active_turn = None

    try:
        events.emit(RunStarted(run_id=run_id, task=task, workspace=str(workspace)))
        while True:
            should_stop, stop_reason, _ = termination.should_stop(state)
            if should_stop:
                if stop_reason is None:
                    raise RuntimeError("termination requested without a stop reason")
                state.mark_stopped(stop_reason)
                events.emit(FeedbackRecorded(
                    run_id=run_id,
                    step=state.step_count,
                    kind="stop",
                    content=stop_reason.value,
                ))
                break

            turn_number += 1
            active_turn = turn_number
            events.emit(TurnStarted(run_id=run_id, turn=turn_number))
            messages = context_manager.build(state, brief)
            repeat_feedback = termination.get_repeated_action_feedback()
            if repeat_feedback:
                messages.append({"role": "user", "content": f"[System Feedback] {repeat_feedback}"})

            model_name = getattr(model_client, "model", "")
            active_model = True
            events.emit(ModelStarted(
                run_id=run_id,
                turn=turn_number,
                step=state.step_count,
                model=model_name,
            ))
            try:
                response = model_client.generate(messages=messages, tools=registry.schemas())
            except Exception as exc:
                events.emit(ModelFailed(
                    run_id=run_id,
                    turn=turn_number,
                    step=state.step_count,
                    model=model_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                ))
                active_model = False
                end_turn(turn_number, "error")
                raise

            state.model_calls += 1
            state.total_input_tokens += response.usage.input_tokens
            state.total_output_tokens += response.usage.output_tokens
            active_model = False
            events.emit(ModelCompleted(
                run_id=run_id,
                turn=turn_number,
                step=state.step_count,
                model=model_name,
                response=ModelResponseSnapshot.from_response(response),
            ))
            action = parser.parse(response)

            if isinstance(action, FinishAction):
                accepted, feedback = finish_policy.check(state, action)
                if not accepted:
                    fb_text = f"[FinishPolicy] {feedback}"
                    context_manager.record_feedback(fb_text)
                    state.consecutive_errors += 1
                    events.emit(FeedbackRecorded(
                        run_id=run_id,
                        step=state.step_count,
                        kind="finish_rejected",
                        content=fb_text,
                    ))
                    state.mark_step_done()
                    end_turn(turn_number, "finish_rejected")
                    continue

                state.mark_finished(action.summary, action.validation, action.validation_skipped_reason)
                events.emit(FinishAccepted(
                    run_id=run_id,
                    turn=turn_number,
                    step=state.step_count,
                    summary=action.summary,
                    validation=action.validation,
                    notes=action.notes,
                    validation_skipped_reason=action.validation_skipped_reason,
                    final_state=_snapshot(state),
                ))
                end_turn(turn_number, "finished")
                break

            if action.is_invalid:
                tool_list = ", ".join(registry.names())
                # P2-1E.1: 协议级失败（截断 / 非法 JSON / 多调用）使用
                # 不同的 feedback kind，便于 trajectory 和调试区分；但仍走
                # [InvalidAction] 高优先级反馈路径，让模型看到明确的错误。
                if action.is_protocol_failure:
                    feedback = (
                        f"[InvalidAction][ProtocolFailure] {action.error_msg}\n"
                        "Your previous response was structurally invalid (truncated, "
                        "malformed, or non-conformant to the tool-call protocol). "
                        f"Available tools: {tool_list}. "
                        "Re-emit a complete, valid response with at most one tool call."
                    )
                    feedback_kind = "protocol_failure"
                else:
                    feedback = (
                        f"[InvalidAction] {action.error_msg}\n"
                        f"Available tools: {tool_list}.\n"
                        "You MUST respond with a valid tool call in your next message. "
                        "Do not output plain text without a tool call."
                    )
                    feedback_kind = "invalid_action"
                context_manager.record_feedback(feedback)
                state.consecutive_errors += 1
                events.emit(FeedbackRecorded(
                    run_id=run_id,
                    step=state.step_count,
                    kind=feedback_kind,
                    content=feedback,
                ))
                state.mark_step_done()
                end_turn(turn_number, "invalid")
                continue

            tool_step = state.step_count
            active_tool = (action, None, tool_step)
            events.emit(ToolStarted(
                run_id=run_id,
                turn=turn_number,
                step=tool_step,
                tool_name=action.tool_name,
                action_id=action.action_id,
                arguments=action.arguments,
            ))
            tool = registry.get(action.tool_name)
            tool_exception: Exception | None = None
            if tool is None:
                observation = ToolResult.fail(
                    f"Unknown tool: '{action.tool_name}'. Available tools: {', '.join(registry.names())}",
                    is_runtime_error=True,
                )
                state.consecutive_errors += 1
            else:
                try:
                    observation = tool.execute(action.arguments, runtime)
                    observation = failure_refresher.maybe_refresh(state, observation)
                    if observation.success:
                        state.consecutive_errors = 0
                    else:
                        state.consecutive_errors += 1
                    state.consecutive_timeouts = (
                        state.consecutive_timeouts + 1 if observation.is_timeout else 0
                    )
                except Exception as exc:
                    tool_exception = exc
                    observation = tool.exception_observation(exc)
                    state.consecutive_errors += 1
            active_tool = (action, observation, tool_step)

            # Commit all core facts before announcing the tool's terminal event.
            state.step_count += 1
            state.tool_calls += 1
            state.record_action(action.tool_name, action.args_hash)
            if action.tool_name in ("apply_patch", "patch"):
                if observation.success and action.arguments.get("path"):
                    path = str(action.arguments["path"])
                    state.record_modified(path)
                    state.add_finding(f"Modified {path}")
                    state.record_mutation(state.step_count)
            elif action.tool_name == "read_file":
                if observation.success and action.arguments.get("path"):
                    state.record_inspected(str(action.arguments["path"]))
            elif action.tool_name == "search_code" and observation.success:
                import re
                match = re.search(r"Found (\d+) matches", observation.content)
                if match:
                    state.add_finding(
                        f"search_code('{action.arguments.get('query', '')}') → {match.group(1)} matches"
                    )
            elif action.tool_name == "run_command":
                if observation.is_validation_failure:
                    state.recent_validation = observation.summary or "test failed"
                    state.add_finding(f"Test failure: {observation.summary or 'see logs'}")
                    state.add_open_question(
                        "Why did the test fail? Inspect modified files and recent test output."
                    )
                command = str(action.arguments.get("command", ""))
                verdict = classify_validation(observation, command)
                if verdict.is_validation:
                    state.record_validation(
                        step=state.step_count,
                        command=command,
                        passed=bool(verdict.passed),
                        summary=verdict.reason,
                    )
            if observation.is_validation_failure:
                state.recent_validation = observation.summary

            result_snapshot = ToolResultSnapshot.from_result(observation)
            if tool_exception is not None or observation.is_runtime_error:
                events.emit(ToolFailed(
                    run_id=run_id,
                    turn=turn_number,
                    step=tool_step,
                    tool_name=action.tool_name,
                    action_id=action.action_id,
                    arguments=action.arguments,
                    args_hash=action.args_hash,
                    error_type=type(tool_exception).__name__ if tool_exception else "RuntimeError",
                    error=observation.error or observation.content,
                    result=result_snapshot,
                ))
            else:
                events.emit(ToolCompleted(
                    run_id=run_id,
                    turn=turn_number,
                    step=tool_step,
                    tool_name=action.tool_name,
                    action_id=action.action_id,
                    arguments=action.arguments,
                    args_hash=action.args_hash,
                    result=result_snapshot,
                ))

            active_tool = None
            if action.tool_name == "run_command":
                command = str(action.arguments.get("command", ""))
                verdict = classify_validation(observation, command)
                if verdict.is_validation:
                    events.emit(ValidationCompleted(
                        run_id=run_id,
                        step=state.step_count,
                        command=command,
                        is_validation=True,
                        passed=verdict.passed,
                        summary=verdict.reason,
                        is_runtime_error=observation.is_runtime_error,
                    ))

            context_manager.record_observation(state, action, observation)
            termination.record_action(
                action.tool_name,
                action.args_hash,
                observation_changed=observation.success,
            )
            state.mark_step_done()
            end_turn(turn_number, "completed")

        events.emit(RunFinished(run_id=run_id, final_state=_snapshot(state)))
    except Exception as exc:
        if active_model:
            active_model = False
            try:
                events.emit(ModelFailed(
                    run_id=run_id,
                    turn=turn_number,
                    step=state.step_count,
                    model=getattr(model_client, "model", ""),
                    error_type=type(exc).__name__,
                    error=str(exc),
                ))
            except Exception:
                pass
        if active_tool is not None:
            active_action = active_tool[0]
            active_observation: ToolResult | None = active_tool[1]
            active_tool_step = active_tool[2]
            active_tool = None
            try:
                events.emit(ToolFailed(
                    run_id=run_id,
                    turn=turn_number,
                    step=active_tool_step,
                    tool_name=active_action.tool_name,
                    action_id=active_action.action_id,
                    arguments=active_action.arguments,
                    args_hash=active_action.args_hash,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    result=ToolResultSnapshot.from_result(active_observation) if active_observation else None,
                ))
            except Exception:
                pass
        if active_turn is not None:
            turn = active_turn
            active_turn = None
            try:
                events.emit(TurnEnded(run_id=run_id, turn=turn, status="error"))
            except Exception:
                pass
        state.status = "ERROR"
        try:
            events.emit(RunFailed(
                run_id=run_id,
                error_type=type(exc).__name__,
                error=str(exc),
                final_state=_snapshot(state, reason=type(exc).__name__),
            ))
        except Exception:
            # Preserve the original exception if terminal persistence has failed.
            pass
        raise

    return AgentRunResult(
        summary=state.finish_summary or "(no summary)",
        validation=state.finish_validation or "",
        stop_reason=state.stop_reason.value if state.stop_reason else "unknown",
        steps=state.step_count,
        total_tokens=state.total_tokens(),
        duration=time.time() - start,
        trajectory_path=trajectory_path,
    )
