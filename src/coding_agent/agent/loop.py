"""AgentLoop：核心控制循环与兼容 runner。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding_agent.agent.brief import TaskBrief, TaskMode
from coding_agent.agent.cancellation import CancellationRequested, CancellationToken
from coding_agent.agent.finish_policy import FinishPolicy, classify_validation
from coding_agent.agent.state import AgentState
from coding_agent.agent.termination import TerminationConfig, TerminationController
from coding_agent.config import AgentConfig
from coding_agent.context.manager import ContextManager
from coding_agent.emitter import EventEmitter
from coding_agent.events import (
    AssistantReplied,
    FeedbackRecorded,
    FinishAccepted,
    ModelCompleted,
    ModelDelta,
    ModelFailed,
    ModelResponseSnapshot,
    ModelStarted,
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStateSnapshot,
    ToolCancelled,
    ToolCompleted,
    ToolFailed,
    ToolOutputDelta,
    ToolResultSnapshot,
    ToolStarted,
    TurnEnded,
    TurnStarted,
    ValidationCompleted,
)
from coding_agent.model.client import ModelClient
from coding_agent.model.parsers.openai_compatible import OpenAICompatibleParser
from coding_agent.model.streaming import ModelStreamAccumulator, ModelStreamDelta
from coding_agent.model.types import AgentAction, AssistantReplyAction, FinishAction, ToolResult
from coding_agent.recovery.failure_refresh import FailureAwareRefresher
from coding_agent.runtime.base import RuntimeOutputChunk, ToolExecutionContext
from coding_agent.runtime.local import LocalRuntime
from coding_agent.session import AgentSession, PreviousRunSnapshot
from coding_agent.tools.registry import default_registry
from coding_agent.trajectory import TrajectoryEventSink, TrajectoryLogger
from coding_agent.workspace.tracker import WorkspaceChangeTracker


@dataclass
class AgentRunResult:
    """一次完整 Agent Run 的最终结果。"""

    summary: str
    validation: str
    stop_reason: str
    steps: int
    total_tokens: int
    duration: float
    reply: str | None = None
    trajectory_path: Path | None = None
    modified_files: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    final_state: RunStateSnapshot | None = None


class _LoopFailure(Exception):
    """Carry the original loop error and its best terminal state outward."""

    def __init__(self, error: Exception, final_state: RunStateSnapshot) -> None:
        super().__init__(str(error))
        self.error = error
        self.final_state = final_state


class _LoopCancelled(Exception):
    """Carry a cancelled run's final state to the outer coordinator."""

    def __init__(self, final_state: RunStateSnapshot) -> None:
        super().__init__("agent run cancelled")
        self.final_state = final_state


def _snapshot(state: AgentState, *, reason: str = "") -> RunStateSnapshot:
    """Build an immutable terminal view without exposing AgentState containers."""
    return RunStateSnapshot(
        status=state.status,
        reason=reason or (state.stop_reason.value if state.stop_reason else ""),
        summary=state.finish_summary or state.reply_text or "",
        validation=state.finish_validation or "",
        validation_skipped_reason=state.finish_validation_skipped_reason or "",
        notes=state.finish_notes or "",
        reply=state.reply_text or "",
        steps=state.step_count,
        total_tokens=state.total_tokens(),
        modified_files=tuple(sorted(state.modified_files)),
        findings=tuple(state.current_findings[-10:]),
    )


def run(
    task: str,
    workspace: Path,
    config: AgentConfig,
    emitter: EventEmitter | None = None,
    task_mode: TaskMode | str | None = None,
    trajectory_sink: TrajectoryEventSink | None = None,
    session: AgentSession | None = None,
    cancellation_token: CancellationToken | None = None,
) -> AgentRunResult:
    """Run one turn, optionally recording it in an :class:`AgentSession`."""
    events = emitter or EventEmitter()
    active_session = session or AgentSession(workspace)
    session_run = active_session.begin_run(task)
    run_id = session_run.run_id
    owns_sink = trajectory_sink is None
    try:
        active_session.record_user(task, run_id=run_id)
        if trajectory_sink is None:
            logger = TrajectoryLogger(
                run_id=run_id,
                workspace=workspace,
                trace_root=config.trace_root,
            )
            trajectory_sink = TrajectoryEventSink(logger)
        events.subscribe(trajectory_sink, critical=True, prepend=True)
        trajectory_path = trajectory_sink.path
        events.emit(RunStarted(
            run_id=run_id,
            session_id=active_session.session_id,
            task=task,
            workspace=str(workspace),
        ))
        try:
            result = _run_loop(
                task=task,
                workspace=workspace,
                config=config,
                events=events,
                task_mode=task_mode,
                trajectory_path=trajectory_path,
                run_id=run_id,
                session_id=active_session.session_id,
                session=active_session,
                cancellation_token=cancellation_token,
            )
        except _LoopCancelled as cancelled:
            _finalize_cancelled_run(
                active_session,
                session_run,
                cancelled.final_state,
                events,
                run_id,
            )
            return AgentRunResult(
                summary=cancelled.final_state.summary,
                validation=cancelled.final_state.validation,
                stop_reason="cancelled",
                steps=cancelled.final_state.steps,
                total_tokens=cancelled.final_state.total_tokens,
                duration=time.time() - getattr(session_run, "started_at", time.time()),
                trajectory_path=trajectory_path,
                modified_files=cancelled.final_state.modified_files,
                findings=cancelled.final_state.findings,
                final_state=cancelled.final_state,
            )
        except _LoopFailure as failure:
            _finalize_failed_run(
                active_session,
                session_run,
                failure.error,
                failure.final_state,
                events,
                run_id,
            )
            raise failure.error from failure.error
        except Exception as exc:
            # Initialization failures happen before AgentState exists. The outer
            # coordinator still closes the Session and publishes one terminal event.
            final_state = RunStateSnapshot(status="ERROR", reason=type(exc).__name__)
            _finalize_failed_run(
                active_session, session_run, exc, final_state, events, run_id
            )
            raise

        # Session persistence is the commit point: observers must not see success
        # until the terminal snapshot and active-run release have both succeeded.
        committed = active_session.complete_run(
            session_run,
            result,
            reason=result.stop_reason,
        )
        result.final_state = RunStateSnapshot(
            status=committed.status or "COMPLETED",
            reason=committed.reason or result.stop_reason,
            summary=committed.summary,
            validation=committed.validation,
            validation_skipped_reason=committed.validation_skipped_reason,
            notes=committed.notes,
            reply=result.reply or "",
            steps=committed.steps,
            total_tokens=committed.total_tokens,
            modified_files=committed.modified_files,
            findings=committed.findings,
        )
        try:
            events.emit(RunFinished(
                run_id=run_id,
                session_id=active_session.session_id,
                final_state=result.final_state,
            ))
        except Exception as delivery_error:
            # The Session is already committed. Publish the sole observable
            # terminal fallback without changing that committed outcome.
            try:
                events.emit(RunFailed(
                    run_id=run_id,
                    session_id=active_session.session_id,
                    error_type=type(delivery_error).__name__,
                    error=str(delivery_error),
                    final_state=result.final_state or RunStateSnapshot(
                        status="COMPLETED", reason=result.stop_reason
                    ),
                ))
            except Exception:
                pass
            raise
        return result
    except _LoopFailure:
        raise
    except Exception as exc:
        # complete_run or terminal delivery failed. A failed commit releases its
        # guard in AgentSession; only publish failure if no terminal was emitted.
        if active_session.is_active:
            _finalize_failed_run(
                active_session,
                session_run,
                exc,
                RunStateSnapshot(status="ERROR", reason=type(exc).__name__),
                events,
                run_id,
            )
        raise
    finally:
        if owns_sink and trajectory_sink is not None:
            events.unsubscribe(trajectory_sink)
            trajectory_sink.close()


def _finalize_cancelled_run(
    session: AgentSession,
    session_run: Any,
    final_state: RunStateSnapshot,
    events: EventEmitter,
    run_id: str,
) -> None:
    """Persist cancellation before exposing the matching terminal event."""
    committed = session.cancel_run(
        session_run,
        snapshot=PreviousRunSnapshot(
            run_id=run_id,
            outcome="cancelled",
            reason="cancelled",
            summary=final_state.summary,
            validation=final_state.validation,
            notes=final_state.notes,
            validation_skipped_reason=final_state.validation_skipped_reason,
            modified_files=final_state.modified_files,
            findings=final_state.findings,
            steps=final_state.steps,
            total_tokens=final_state.total_tokens,
            status="CANCELLED",
        ),
    )
    events.emit(RunCancelled(
        run_id=run_id,
        session_id=session.session_id,
        final_state=RunStateSnapshot(
            status=committed.status or "CANCELLED",
            reason=committed.reason or "cancelled",
            summary=committed.summary,
            validation=committed.validation,
            notes=committed.notes,
            validation_skipped_reason=committed.validation_skipped_reason,
            steps=committed.steps,
            total_tokens=committed.total_tokens,
            modified_files=committed.modified_files,
            findings=committed.findings,
        ),
    ))

def _finalize_failed_run(
    session: AgentSession,
    session_run: Any,
    error: Exception,
    final_state: RunStateSnapshot,
    events: EventEmitter,
    run_id: str,
) -> None:
    """Persist failure before exposing the matching terminal lifecycle event."""
    try:
        committed = session.fail_run(session_run, error, snapshot=PreviousRunSnapshot(
            run_id=run_id,
            outcome="failed",
            reason=final_state.reason or type(error).__name__,
            summary=final_state.summary,
            validation=final_state.validation,
            notes=final_state.notes,
            validation_skipped_reason=final_state.validation_skipped_reason,
            error=str(error),
            modified_files=final_state.modified_files,
            findings=final_state.findings,
            steps=final_state.steps,
            total_tokens=final_state.total_tokens,
            status="ERROR",
        ))
    except Exception:
        # AgentSession releases its active guard even when finalization fails.
        # Keep the original run error as the caller-visible exception.
        return
    try:
        events.emit(RunFailed(
            run_id=run_id,
            session_id=session.session_id,
            error_type=type(error).__name__,
            error=str(error),
            final_state=RunStateSnapshot(
                status=committed.status or "ERROR",
                reason=committed.reason or type(error).__name__,
                summary=committed.summary,
                validation=committed.validation,
                notes=committed.notes,
                validation_skipped_reason=committed.validation_skipped_reason,
                reply=final_state.reply,
                steps=committed.steps,
                total_tokens=committed.total_tokens,
                modified_files=committed.modified_files,
                findings=committed.findings,
            ),
        ))
    except Exception:
        # Terminal delivery errors must not mask the original run exception.
        return


def _run_loop(
    task: str,
    workspace: Path,
    config: AgentConfig,
    events: EventEmitter,
    task_mode: TaskMode | str | None = None,
    trajectory_path: Path | None = None,
    run_id: str | None = None,
    session_id: str = "",
    session: AgentSession | None = None,
    cancellation_token: CancellationToken | None = None,
) -> AgentRunResult:
    """Execute the AgentLoop; all observability is emitted as typed events."""
    start = time.time()
    run_id = run_id or f"run_{int(start)}_{uuid.uuid4().hex[:6]}"
    token = cancellation_token or CancellationToken()
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
    # P2-1E.3：所有 tool 都共享一个 workspace 变化跟踪器，
    # 真实净变化（shell / formatter / generator / untracked / permission）
    # 都进入 modified_files，不再按 tool name 猜 mutation。
    workspace_tracker = WorkspaceChangeTracker(workspace)

    def end_turn(turn: int, status: str) -> None:
        nonlocal active_turn
        events.emit(TurnEnded(run_id=run_id, turn=turn, status=status))
        active_turn = None

    try:
        while True:
            token.raise_if_cancelled()
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
            try:
                token.raise_if_cancelled()
                messages = context_manager.build(
                    state,
                    brief,
                    session=session,
                    current_run_id=run_id,
                )
            except TypeError as exc:
                # Keep compatibility with injected/monkeypatched legacy context
                # managers that still implement build(state, brief).
                if "unexpected keyword argument" not in str(exc):
                    raise
                messages = context_manager.build(state, brief)
            repeat_feedback = termination.get_repeated_action_feedback()
            if repeat_feedback:
                messages.append({"role": "user", "content": f"[System Feedback] {repeat_feedback}"})

            model_name = getattr(model_client, "model", "")
            token.raise_if_cancelled()
            active_model = True
            events.emit(ModelStarted(
                run_id=run_id,
                turn=turn_number,
                step=state.step_count,
                model=model_name,
            ))
            try:
                stream_method = getattr(model_client, "generate_stream", None)
                if callable(stream_method) and getattr(model_client, "supports_streaming", False):
                    accumulator = ModelStreamAccumulator()
                    for delta in stream_method(messages=messages, tools=registry.schemas()):
                        token.raise_if_cancelled()
                        if not isinstance(delta, ModelStreamDelta):
                            raise TypeError(
                                "ModelClient.generate_stream must yield ModelStreamDelta values"
                            )
                        accumulator.add(delta)
                        events.emit(ModelDelta(
                            run_id=run_id,
                            turn=turn_number,
                            step=state.step_count,
                            model=model_name,
                            text=delta.text,
                            tool_call_index=delta.tool_call_index,
                            tool_call_id=delta.tool_call_id,
                            tool_name=delta.tool_name,
                            arguments_delta=delta.arguments_delta,
                        ))
                    response = accumulator.finish()
                else:
                    response = model_client.generate(messages=messages, tools=registry.schemas())
            except CancellationRequested:
                active_model = False
                raise
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
            token.raise_if_cancelled()
            action = parser.parse(response)
            token.raise_if_cancelled()

            if isinstance(action, AssistantReplyAction):
                if state.last_mutation_step > 0:
                    feedback = (
                        "A workspace mutation occurred in this run. Do not finish with "
                        "plain text; run validation and call finish(summary, validation)."
                    )
                    context_manager.record_feedback(f"[FinishPolicy] {feedback}")
                    state.consecutive_errors += 1
                    events.emit(FeedbackRecorded(
                        run_id=run_id,
                        step=state.step_count,
                        kind="finish_rejected",
                        content=f"[FinishPolicy] {feedback}",
                    ))
                    state.mark_step_done()
                    end_turn(turn_number, "reply_rejected")
                    continue

                state.mark_answered(action.reply_text)
                if session is not None:
                    session.record_assistant(action.reply_text, run_id=run_id)
                events.emit(AssistantReplied(
                    run_id=run_id,
                    turn=turn_number,
                    step=state.step_count,
                    text=action.reply_text,
                    final_state=_snapshot(state),
                ))
                end_turn(turn_number, "answered")
                break

            if isinstance(action, FinishAction):
                accepted, feedback_value = finish_policy.check(state, action)
                if not accepted:
                    fb_text = f"[FinishPolicy] {feedback_value}"
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

                state.mark_finished(action.summary, action.validation, action.validation_skipped_reason, action.notes)
                token.raise_if_cancelled()
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
            token.raise_if_cancelled()
            active_tool = (action, None, tool_step)
            if session is not None:
                session.record_tool_call(
                    tool_call_id=action.action_id,
                    tool_name=action.tool_name,
                    arguments=action.arguments,
                    content=action.preamble,
                    run_id=run_id,
                )
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
            # P2-1E.3：所有 tool 前后做 workspace 快照比对，真实净变化
            # 才是 mutation；不再按 tool name 猜。read_file / list_files /
            # search_code 等只读工具理论上不会触发变化，但 cheap 防御性
            # 保留 snapshot 仍然正确。
            prev_snapshot = workspace_tracker.snapshot()

            def _on_output(
                chunk: RuntimeOutputChunk,
                _run_id: str = run_id,
                _turn: int = turn_number,
                _step: int = tool_step,
                _tool_name: str = action.tool_name,
                _action_id: str = action.action_id,
            ) -> None:
                events.emit(ToolOutputDelta(
                    run_id=_run_id,
                    turn=_turn,
                    step=_step,
                    tool_name=_tool_name,
                    action_id=_action_id,
                    text=chunk.text,
                    chunk_index=chunk.chunk_index,
                    stream=chunk.stream,
                ))

            execution_context = ToolExecutionContext(
                cancellation_token=token,
                on_output=_on_output,
            )
            if tool is None:
                observation = ToolResult.fail(
                    f"Unknown tool: '{action.tool_name}'. Available tools: {', '.join(registry.names())}",
                    is_runtime_error=True,
                )
                state.consecutive_errors += 1
            else:
                try:
                    if action.tool_name == "run_command":
                        observation = tool.execute(
                            action.arguments, runtime, context=execution_context
                        )
                    else:
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
            if session is not None:
                session.record_tool_result(
                    tool_call_id=action.action_id,
                    tool_name=action.tool_name,
                    content=observation.content,
                    success=observation.success,
                    error=observation.error,
                    run_id=run_id,
                )
            workspace_change = workspace_tracker.diff_since(prev_snapshot)

            # Commit all core facts before announcing the tool's terminal event.
            state.step_count += 1
            state.tool_calls += 1
            state.record_action(action.tool_name, action.args_hash)
            # P2-1E.3：mutation 检测统一走 tracker。
            if workspace_change.has_changes:
                state.record_workspace_change(workspace_change, state.step_count)
                for path in workspace_change.all_paths():
                    state.add_finding(
                        f"workspace change: {path} ({workspace_change.summary()})"
                    )
            if action.tool_name == "read_file":
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
            terminal_emitted = False
            if action.tool_name == "run_command" and observation.is_timeout:
                # Timeout or cooperative cancellation: emit ``ToolCancelled``
                # as the authoritative durable boundary so observers do not
                # treat a stopped-by-user/cancelled-by-deadline tool as a
                # generic runtime failure. ``is_runtime_error`` may also be
                # True in this state (LocalRuntime marks cancelled exits as
                # runtime errors), so this branch must precede the generic
                # failure branch.
                events.emit(ToolCancelled(
                    run_id=run_id,
                    turn=turn_number,
                    step=tool_step,
                    tool_name=action.tool_name,
                    action_id=action.action_id,
                    arguments=action.arguments,
                    args_hash=action.args_hash,
                    result=result_snapshot,
                    reason=observation.error or "cancelled",
                ))
                terminal_emitted = True
            elif tool_exception is not None or observation.is_runtime_error:
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
                terminal_emitted = True
            if not terminal_emitted:
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
            token.raise_if_cancelled()
            end_turn(turn_number, "completed")

    except Exception as exc:
        if isinstance(exc, CancellationRequested):
            if active_tool is not None:
                active_action = active_tool[0]
                active_observation = active_tool[1]
                active_tool_step = active_tool[2]
                active_tool = None
                if session is not None and active_observation is not None:
                    session.record_tool_result(
                        tool_call_id=active_action.action_id,
                        tool_name=active_action.tool_name,
                        content=active_observation.content,
                        success=active_observation.success,
                        error=active_observation.error,
                        run_id=run_id,
                    )
                try:
                    events.emit(ToolCancelled(
                        run_id=run_id,
                        turn=turn_number,
                        step=active_tool_step,
                        tool_name=active_action.tool_name,
                        action_id=active_action.action_id,
                        arguments=active_action.arguments,
                        args_hash=active_action.args_hash,
                        result=ToolResultSnapshot.from_result(active_observation)
                        if active_observation else None,
                        reason="cancelled",
                    ))
                except Exception:
                    pass
            if active_model:
                active_model = False
            if active_turn is not None:
                try:
                    events.emit(TurnEnded(run_id=run_id, turn=active_turn, status="cancelled"))
                except Exception:
                    pass
            state.mark_cancelled()
            raise _LoopCancelled(_snapshot(state, reason="cancelled")) from exc
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
            active_observation = active_tool[1]
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
        raise _LoopFailure(exc, _snapshot(state, reason=type(exc).__name__)) from exc

    return AgentRunResult(
        summary=state.finish_summary or state.reply_text or "(no summary)",
        validation=state.finish_validation or "",
        reply=state.reply_text,
        stop_reason=state.stop_reason.value if state.stop_reason else "unknown",
        steps=state.step_count,
        total_tokens=state.total_tokens(),
        duration=time.time() - start,
        trajectory_path=trajectory_path,
        modified_files=tuple(sorted(state.modified_files)),
        findings=tuple(state.current_findings[-10:]),
        final_state=_snapshot(state),
    )
