"""Thread and Textual message bridge for Agent lifecycle events."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual.message import Message

from coding_agent.agent.brief import TaskMode
from coding_agent.agent.loop import AgentRunResult
from coding_agent.agent.loop import run as agent_run
from coding_agent.config import AgentConfig
from coding_agent.emitter import EventEmitter
from coding_agent.events import AgentEvent

_log = logging.getLogger(__name__)


class UiAgentEvent(Message):
    """A lifecycle event queued for handling by the Textual app thread."""

    def __init__(self, event: AgentEvent) -> None:
        super().__init__()
        self.event = event


class AgentWorkerResult(Message):
    """Posted by :class:`AgentWorker` after a successful run."""

    def __init__(self, result: AgentRunResult) -> None:
        super().__init__()
        self.result = result


class AgentWorkerError(Message):
    """Posted by :class:`AgentWorker` after an uncaught run exception."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error


class TuiEventSink:
    """Best-effort EventEmitter sink that posts messages to a Textual owner.

    ``EventEmitter`` invokes sinks synchronously on the Agent worker thread.
    Textual's ``post_message`` is the only operation performed here: the sink
    never queries, mutates, or renders a widget. Textual copies the message
    into the app queue when called from another thread.
    """

    critical = False

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def __call__(self, event: AgentEvent) -> None:
        try:
            queued = self.owner.post_message(UiAgentEvent(event))
        except Exception:
            _log.exception("TUI event sink failed for %s", event.event_type)
            return
        if queued is False:
            _log.debug("TUI event was not queued for %s", event.event_type)


class AgentWorker:
    """Run the synchronous AgentLoop on a daemon thread.

    The worker owns no Textual widget references beyond the message owner used
    by ``TuiEventSink``. All callbacks back into the app are Textual messages,
    so application code handles them on the app thread.
    """

    def __init__(
        self,
        owner: Any,
        *,
        task: str,
        workspace: Path,
        config: AgentConfig,
        task_mode: TaskMode | str | None = None,
        run_fn: Callable[..., AgentRunResult] = agent_run,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self.owner = owner
        self.task = task
        self.workspace = workspace
        self.config = config
        self.task_mode = task_mode
        self.run_fn = run_fn
        self.thread_factory = thread_factory
        self.emitter = EventEmitter()
        self.sink = TuiEventSink(owner)
        self.thread: threading.Thread | None = None

    @property
    def is_alive(self) -> bool:
        """Whether the worker thread is currently executing."""
        return self.thread is not None and self.thread.is_alive()

    def start(self) -> threading.Thread:
        """Start the worker exactly once and return its thread."""
        if self.thread is not None:
            raise RuntimeError("agent worker has already started")
        self.emitter.subscribe(self.sink)
        self.thread = self.thread_factory(
            target=self._run,
            name="traceforce-agent-worker",
            daemon=True,
        )
        self.thread.start()
        return self.thread

    def _run(self) -> None:
        try:
            result = self.run_fn(
                task=self.task,
                workspace=self.workspace,
                config=self.config,
                emitter=self.emitter,
                task_mode=self.task_mode,
            )
        except Exception as exc:
            self._post(AgentWorkerError(exc))
        else:
            self._post(AgentWorkerResult(result))

    def _post(self, message: Message) -> None:
        """Post a completion message without allowing UI failures to escape."""
        try:
            self.owner.post_message(message)
        except Exception:
            _log.exception("could not post agent worker message")


__all__ = [
    "AgentWorker",
    "AgentWorkerError",
    "AgentWorkerResult",
    "TuiEventSink",
    "UiAgentEvent",
]
