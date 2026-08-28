"""Synchronous lifecycle event emitter and test collector."""

from __future__ import annotations

import logging
from collections.abc import Callable

from coding_agent.events import AgentEvent, BaseEvent


_log = logging.getLogger(__name__)
EventSink = Callable[[AgentEvent], None]


class EventEmitter:
    """Emit events synchronously to subscribers in registration order."""

    def __init__(self, *, on_sink_error: Callable[[EventSink, Exception, AgentEvent], None] | None = None):
        self._sinks: list[EventSink] = []
        self._sequence = 0
        self._on_sink_error = on_sink_error

    @property
    def sequence(self) -> int:
        return self._sequence

    def subscribe(self, sink: EventSink) -> EventSink:
        if sink not in self._sinks:
            self._sinks.append(sink)
        return sink

    def unsubscribe(self, sink: EventSink) -> None:
        try:
            self._sinks.remove(sink)
        except ValueError:
            pass

    def emit(self, event: BaseEvent) -> AgentEvent:
        self._sequence += 1
        assigned = event
        if event.sequence != self._sequence:
            assigned = type(event)(**{**event.__dict__, "sequence": self._sequence})
        for sink in tuple(self._sinks):
            try:
                sink(assigned)
            except Exception as exc:  # sinks are observers, never loop control
                _log.exception("Event sink failed for %s", assigned.event_type)
                if self._on_sink_error is not None:
                    try:
                        self._on_sink_error(sink, exc, assigned)
                    except Exception:
                        _log.exception("Event sink error handler failed")
        return assigned


class EventCollector:
    """In-memory sink useful for tests and future adapters."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


__all__ = ["EventCollector", "EventEmitter", "EventSink"]
