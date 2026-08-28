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
from coding_agent.model.types import FinishAction, ToolResult
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

    This compatibility wrapper is the outer runner for the synchronous API. The
    loop itself never creates, writes, or closes a ``TrajectoryLogger``.
    Callers may inject a sink; injected sinks are observed but not owned here.
    """
    events = emitter or EventEmitter()
    owns_sink = trajectory_sink is None
    run_id = f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    if trajectory_sink is None:
        logger = TrajectoryLogger(
            run_id=run_id,
            workspace=workspace,
            trace_root=config.trace_root,
        )
        trajectory_sink = TrajectoryEventSink(logger)
    else:
        run_id = getattr(getattr(trajectory_sink, "logger", None), "run_id", run_id)
    events.subscribe(trajectory_sink, critical=True)
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
            events.emit(TurnStarted(run_id=run_id, turn=turn_number))
            messages = context_manager.build(state, brief)
            repeat_feedback = termination.get_repeated_action_feedback()
            if repeat_feedback:
                messages.append({"role": "user", "content": f"[System Feedback] {repeat_feedback}"})

            model_name = getattr(model_client, "model", "")
            events.emit(ModelStarted(run_id=run_id, turn=turn_number, model=model_name))
            try:
                response = model_client.generate(messages=messages, tools=registry.schemas())
            except Exception as exc:
                events.emit(ModelFailed(
                    run_id=run_id,
                    turn=turn_number,
                    model=model_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                ))
                events.emit(TurnEnded(run_id=run_id, turn=turn_number, status="error"))
                raise

            state.model_calls += 1
            state.total_input_tokens += response.usage.input_tokens
            state.total_output_tokens += response.usage.output_tokens
            events.emit(ModelCompleted(
                run_id=run_id,
                turn=turn_number,
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
                    events.emit(TurnEnded(
                        run_id=run_id, turn=turn_number, status="finish_rejected"
                    ))
                    continue

                state.mark_finished(action.summary, action.validation, action.validation_skipped_reason)
                events.emit(FinishAccepted(
                    run_id=run_id,
                    turn=turn_number,
                    summary=action.summary,
                    validation=action.validation,
                    notes=action.notes,
                    validation_skipped_reason=action.validation_skipped_reason,
                ))
                events.emit(TurnEnded(run_id=run_id, turn=turn_number, status="finished"))
                break

            if action.is_invalid:
                tool_list = ", ".join(registry.names())
                feedback = (
                    f"[InvalidAction] {action.error_msg}\n"
                    f"Available tools: {tool_list}.\n"
                    "You MUST respond with a valid tool call in your next message. "
                    "Do not output plain text without a tool call."
                )
                context_manager.record_feedback(feedback)
                state.consecutive_errors += 1
                events.emit(FeedbackRecorded(
                    run_id=run_id,
                    step=state.step_count,
                    kind="invalid_action",
                    content=feedback,
                ))
                state.mark_step_done()
                events.emit(TurnEnded(run_id=run_id, turn=turn_number, status="invalid"))
                continue

            events.emit(ToolStarted(
                run_id=run_id,
                turn=turn_number,
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

            result_snapshot = ToolResultSnapshot.from_result(observation)
            if tool_exception is not None or observation.is_runtime_error:
                events.emit(ToolFailed(
                    run_id=run_id,
                    turn=turn_number,
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
                    tool_name=action.tool_name,
                    action_id=action.action_id,
                    arguments=action.arguments,
                    args_hash=action.args_hash,
                    result=result_snapshot,
                ))

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
                    passed = bool(verdict.passed)
                    state.record_validation(
                        step=state.step_count,
                        command=command,
                        passed=passed,
                        summary=verdict.reason,
                    )
                    events.emit(ValidationCompleted(
                        run_id=run_id,
                        step=state.step_count,
                        command=command,
                        is_validation=True,
                        passed=verdict.passed,
                        summary=verdict.reason,
                        is_runtime_error=observation.is_runtime_error,
                    ))

            if observation.is_validation_failure:
                state.recent_validation = observation.summary
            context_manager.record_observation(state, action, observation)
            termination.record_action(
                action.tool_name,
                action.args_hash,
                observation_changed=observation.success,
            )
            state.mark_step_done()
            events.emit(TurnEnded(run_id=run_id, turn=turn_number, status="completed"))

    except Exception as exc:
        state.status = "ERROR"
        try:
            events.emit(RunFailed(
                run_id=run_id,
                error_type=type(exc).__name__,
                error=str(exc),
                final_state=_snapshot(state, reason=type(exc).__name__),
            ))
        except Exception:
            # A failed critical sink is already unhealthy; preserve the original
            # exception rather than replacing it with terminal-event delivery.
            pass
        raise

    events.emit(RunFinished(run_id=run_id, final_state=_snapshot(state)))
    return AgentRunResult(
        summary=state.finish_summary or "(no summary)",
        validation=state.finish_validation or "",
        stop_reason=state.stop_reason.value if state.stop_reason else "unknown",
        steps=state.step_count,
        total_tokens=state.total_tokens(),
        duration=time.time() - start,
        trajectory_path=trajectory_path,
    )
