"""Cooperative cancellation primitives for one Agent run."""

from __future__ import annotations

import threading


class CancellationRequested(Exception):
    """Raised at a safe boundary after a run cancellation was requested."""


class CancellationToken:
    """Thread-safe, idempotent cancellation signal owned by one run."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> bool:
        """Request cancellation; return True only for the first request."""
        with self._lock:
            if self._event.is_set():
                return False
            self._event.set()
            return True

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise the private control-flow exception at a safe boundary."""
        if self.is_cancelled:
            raise CancellationRequested("agent run cancellation requested")


__all__ = ["CancellationRequested", "CancellationToken"]
