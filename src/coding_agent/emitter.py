"""Synchronous lifecycle event emitter and test collector."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

from coding_agent.events import AgentEvent, BaseEvent

_log = logging.getLogger(__name__)
EventSink = Callable[[AgentEvent], None]


class CriticalEventDeliveryError(RuntimeError):
    """One or more critical event sinks could not consume an event."""

    def __init__(self, errors: list[tuple[EventSink, Exception, AgentEvent]]):
        self.errors = errors
        details = "; ".join(f"{type(error).__name__}: {error}" for _, error, _ in errors)
        super().__init__(f"critical event sink failure: {details}")


class EventEmitter:
    """Emit immutable event snapshots synchronously in registration order."""

    def __init__(
        self,
        *,
        on_sink_error: Callable[[EventSink, Exception, AgentEvent], None] | None = None,
    ):
        self._sinks: list[EventSink] = []
        self._sequence = 0
        self._on_sink_error = on_sink_error
        self._critical_sinks: set[EventSink] = set()
        self._unhealthy_sinks: set[EventSink] = set()

    @property
    def sequence(self) -> int:
        return self._sequence

    def subscribe(self, sink: EventSink, *, critical: bool = False) -> EventSink:
        if sink not in self._sinks:
            self._sinks.append(sink)
        if critical or bool(getattr(sink, "critical", False)):
            self._critical_sinks.add(sink)
        return sink

    def unsubscribe(self, sink: EventSink) -> None:
        try:
            self._sinks.remove(sink)
        except ValueError:
            pass
        self._critical_sinks.discard(sink)
        self._unhealthy_sinks.discard(sink)

    def emit(self, event: BaseEvent) -> AgentEvent:
        self._sequence += 1
        assigned: AgentEvent = replace(event, sequence=self._sequence)  # type: ignore[assignment]
        errors: list[tuple[EventSink, Exception, AgentEvent]] = []
        for sink in tuple(self._sinks):
            if sink in self._unhealthy_sinks:
                continue
            try:
                sink(assigned)
            except Exception as exc:  # sinks never interrupt sibling sinks
                _log.exception("Event sink failed for %s", assigned.event_type)
                if sink in self._critical_sinks:
                    self._unhealthy_sinks.add(sink)
                    errors.append((sink, exc, assigned))
                elif self._on_sink_error is not None:
                    try:
                        self._on_sink_error(sink, exc, assigned)
                    except Exception:
                        _log.exception("Event sink error handler failed")
        if errors:
            raise CriticalEventDeliveryError(errors)
        return assigned


class EventCollector:
    """In-memory sink useful for tests and future adapters."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


__all__ = ["CriticalEventDeliveryError", "EventCollector", "EventEmitter", "EventSink"]
