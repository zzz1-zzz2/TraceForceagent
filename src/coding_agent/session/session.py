"""In-memory orchestration state for a multi-run agent session."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from .types import (
    MAX_MESSAGE_CONTENT_CHARS,
    PreviousRunSnapshot,
    SessionActiveError,
    SessionCapacityError,
    SessionMessage,
    SessionRun,
    SessionStateError,
)


class AgentSession:
    """Own complete history and run coordination for one workspace.

    The session is deliberately independent of ``AgentConfig`` and model clients.
    It is an in-memory orchestration boundary: messages are facts, while the
    context manager decides which facts fit in a particular model request.
    """

    def __init__(
        self,
        workspace: Path | str,
        *,
        session_id: str | None = None,
        max_messages: int | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.session_id = session_id or f"session_{uuid.uuid4().hex}"
        if not self.session_id:
            raise ValueError("session_id cannot be empty")
        if max_messages is not None and max_messages < 1:
            raise ValueError("max_messages must be positive")
        self.max_messages = max_messages
        self._messages: list[SessionMessage] = []
        self._runs: list[SessionRun] = []
        self._active_run_id: str | None = None
        self._snapshot: PreviousRunSnapshot | None = None
        self._lock = RLock()

    @property
    def messages(self) -> tuple[SessionMessage, ...]:
        """Return the complete immutable history; context trimming never mutates it."""
        with self._lock:
            return tuple(self._messages)

    @property
    def history(self) -> tuple[SessionMessage, ...]:
        """Alias for :attr:`messages`."""
        return self.messages

    @property
    def runs(self) -> tuple[SessionRun, ...]:
        with self._lock:
            return tuple(self._runs)

    @property
    def snapshot(self) -> PreviousRunSnapshot | None:
        with self._lock:
            return self._snapshot

    @property
    def previous_run(self) -> PreviousRunSnapshot | None:
        """Alias for the most recently completed or failed run summary."""
        return self.snapshot

    @property
    def active_run(self) -> SessionRun | None:
        with self._lock:
            if self._active_run_id is None:
                return None
            return self._find_run(self._active_run_id)

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return self._active_run_id

    @property
    def is_active(self) -> bool:
        return self.active_run_id is not None

    def begin_run(self, task: str) -> SessionRun:
        """Create the sole authoritative run id for a new run."""
        task_text = str(task or "")
        if not task_text.strip():
            raise ValueError("run task cannot be empty")
        # Validate the absolute task limit before changing active-run state.
        if len(task_text) > MAX_MESSAGE_CONTENT_CHARS:
            raise SessionCapacityError(
                f"task exceeds the session limit of {MAX_MESSAGE_CONTENT_CHARS} characters"
            )
        with self._lock:
            if self._active_run_id is not None:
                raise SessionActiveError(
                    f"session already has active run {self._active_run_id}"
                )
            run_id = f"run_{uuid.uuid4().hex}"
            run = SessionRun(run_id=run_id, task=task_text)
            self._runs.append(run)
            self._active_run_id = run_id
            return run

    def record(self, message: SessionMessage) -> SessionMessage:
        """Append one immutable fact without silently evicting old history."""
        if not isinstance(message, SessionMessage):
            raise TypeError("session history accepts SessionMessage values only")
        with self._lock:
            self._append_message_locked(message)
        return message

    def _append_message_locked(self, message: SessionMessage) -> None:
        """Validate and append a fact while the session lock is held."""
        self._validate_message(message)
        self._ensure_message_capacity()
        self._messages.append(message)

    def _validate_message(self, message: SessionMessage) -> None:
        self._require_active_run(message.run_id)
        if message.role == "assistant" and message.tool_call_id:
            if not message.tool_name:
                raise SessionStateError("tool call requires tool_call_id and tool_name")
            if any(
                prior.role == "assistant"
                and prior.run_id == message.run_id
                and prior.tool_call_id == message.tool_call_id
                for prior in self._messages
            ):
                raise SessionStateError(
                    f"tool call {message.tool_call_id} was already recorded"
                )
            return

        if message.role == "tool":
            if not message.tool_call_id or not message.tool_name:
                raise SessionStateError("tool result requires tool_call_id and tool_name")
            matching_call = next(
                (
                    prior
                    for prior in self._messages
                    if prior.role == "assistant"
                    and prior.run_id == message.run_id
                    and prior.tool_call_id == message.tool_call_id
                ),
                None,
            )
            if matching_call is None:
                raise SessionStateError(
                    f"tool result {message.tool_call_id} has no matching tool call"
                )
            if matching_call.tool_name != message.tool_name:
                raise SessionStateError(
                    f"tool result {message.tool_call_id} names {message.tool_name!r}, "
                    f"expected {matching_call.tool_name!r}"
                )
            if any(
                prior.role == "tool"
                and prior.run_id == message.run_id
                and prior.tool_call_id == message.tool_call_id
                for prior in self._messages
            ):
                raise SessionStateError(
                    f"tool result {message.tool_call_id} was already recorded"
                )
        elif message.tool_call_id or message.tool_name or message.tool_result:
            raise SessionStateError("tool metadata is only valid for tool facts")

    def record_message(
        self,
        role: str,
        content: str = "",
        *,
        run_id: str | None = None,
        tool_call_id: str = "",
        tool_name: str = "",
        arguments: Mapping[str, Any] | None = None,
        tool_result: str = "",
        success: bool | None = None,
        error: str = "",
    ) -> SessionMessage:
        """Construct and append one message fact atomically."""
        with self._lock:
            actual_run_id = run_id or self._required_active_run_id()
            message = SessionMessage(
                role=role,
                content=content,
                run_id=actual_run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments or {},
                tool_result=tool_result,
                success=success,
                error=error,
            )
            self._append_message_locked(message)
            return message

    def record_user(self, content: str, *, run_id: str | None = None) -> SessionMessage:
        return self.record_message("user", content, run_id=run_id)

    record_user_message = record_user

    def record_assistant(
        self,
        content: str,
        *,
        run_id: str | None = None,
    ) -> SessionMessage:
        return self.record_message("assistant", content, run_id=run_id)

    record_assistant_reply = record_assistant

    def record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        content: str = "",
        run_id: str | None = None,
    ) -> SessionMessage:
        if not tool_call_id or not tool_name:
            raise SessionStateError("tool call requires tool_call_id and tool_name")
        return self.record_message(
            "assistant",
            content,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
        )

    def record_tool_result(
        self,
        *,
        tool_call_id: str,
        content: str,
        success: bool,
        error: str = "",
        tool_name: str = "",
        run_id: str | None = None,
    ) -> SessionMessage:
        return self.record_message(
            "tool",
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_result=content,
            content=content,
            success=success,
            error=error,
        )

    def complete_run(
        self,
        run_id: str | SessionRun,
        result: Any = None,
        *,
        snapshot: PreviousRunSnapshot | None = None,
        reason: str = "",
    ) -> PreviousRunSnapshot:
        """Commit a successful terminal fact, then release the active guard."""
        return self._finish_run(
            run_id,
            result,
            snapshot=snapshot,
            outcome="completed",
            reason=reason,
            error="",
        )

    def fail_run(
        self,
        run_id: str | SessionRun,
        error: Exception | str | None = None,
        result: Any = None,
        *,
        snapshot: PreviousRunSnapshot | None = None,
        reason: str = "",
    ) -> PreviousRunSnapshot:
        """Commit a failed terminal fact, then release the active guard."""
        error_text = str(error or "")
        return self._finish_run(
            run_id,
            result,
            snapshot=snapshot,
            outcome="failed",
            reason=reason,
            error=error_text,
        )

    def cancel_run(
        self,
        run_id: str | SessionRun,
        result: Any = None,
        *,
        snapshot: PreviousRunSnapshot | None = None,
        reason: str = "cancelled",
    ) -> PreviousRunSnapshot:
        """Commit a cancelled terminal fact, then release the active guard."""
        return self._finish_run(
            run_id,
            result,
            snapshot=snapshot,
            outcome="cancelled",
            reason=reason,
            error="",
        )

    def _finish_run(
        self,
        run_id: str | SessionRun,
        facts: Any,
        *,
        snapshot: PreviousRunSnapshot | None,
        outcome: str,
        reason: str,
        error: str,
    ) -> PreviousRunSnapshot:
        actual_id = run_id.run_id if isinstance(run_id, SessionRun) else str(run_id)
        with self._lock:
            self._require_active_run(actual_id)
            try:
                if snapshot is not None and not isinstance(snapshot, PreviousRunSnapshot):
                    raise TypeError("snapshot must be a PreviousRunSnapshot")
                if outcome == "completed":
                    unresolved = {
                        message.tool_call_id
                        for message in self._messages
                        if message.role == "assistant"
                        and message.tool_call_id
                        and not any(
                            result.role == "tool"
                            and result.run_id == message.run_id
                            and result.tool_call_id == message.tool_call_id
                            for result in self._messages
                        )
                    }
                    if unresolved:
                        raise SessionStateError(
                            "cannot complete run with unresolved tool calls: "
                            + ", ".join(sorted(unresolved))
                        )
                committed = snapshot or PreviousRunSnapshot.from_facts(
                    actual_id,
                    facts,
                    outcome=outcome,
                    reason=reason,
                    error=error,
                )
                index = self._run_index(actual_id)
                prior = self._runs[index]
                self._runs[index] = SessionRun(
                    run_id=prior.run_id,
                    task=prior.task,
                    status=outcome,
                    started_at=prior.started_at,
                    ended_at=time.time(),
                    snapshot=committed,
                )
                self._snapshot = committed
                return committed
            finally:
                # Any exception in snapshot construction or run commit must not
                # strand the session in a permanently active state.
                self._active_run_id = None

    def clear(self) -> None:
        """Clear all history only when no worker can still append to it."""
        with self._lock:
            if self._active_run_id is not None:
                raise SessionActiveError(
                    f"cannot clear session while run {self._active_run_id} is active"
                )
            self._messages.clear()
            self._runs.clear()
            self._snapshot = None

    def _ensure_message_capacity(self) -> None:
        if self.max_messages is not None and len(self._messages) >= self.max_messages:
            raise SessionCapacityError(
                f"session history capacity {self.max_messages} reached; "
                "history will not be silently discarded"
            )

    def _required_active_run_id(self) -> str:
        if self._active_run_id is None:
            raise SessionStateError("recording a session message requires an active run")
        return self._active_run_id

    def _require_active_run(self, run_id: str) -> None:
        if self._active_run_id != run_id:
            if self._active_run_id is None:
                raise SessionStateError(f"run {run_id} is not active")
            raise SessionActiveError(
                f"run {run_id} is not the active run ({self._active_run_id})"
            )

    def _find_run(self, run_id: str) -> SessionRun:
        for run in self._runs:
            if run.run_id == run_id:
                return run
        raise SessionStateError(f"unknown session run {run_id}")

    def _run_index(self, run_id: str) -> int:
        for index, run in enumerate(self._runs):
            if run.run_id == run_id:
                return index
        raise SessionStateError(f"unknown session run {run_id}")


__all__ = ["AgentSession"]
