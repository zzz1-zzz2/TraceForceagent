"""Provider-neutral model streaming primitives.

The provider adapter owns chunk-shape normalization; the accumulator owns the
protocol boundary.  Text and tool arguments are transient deltas while the
completed :class:`ModelResponse` is the durable value consumed by the parser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall


@dataclass(frozen=True, slots=True)
class ModelStreamDelta:
    """One normalized increment from a provider stream.

    A delta may contain text, one indexed tool-call fragment, a finish reason,
    and/or usage.  Provider-specific response objects must not cross this
    boundary.
    """

    text: str = ""
    tool_call_index: int | None = None
    tool_call_id: str = ""
    tool_name: str = ""
    arguments_delta: str = ""
    finish_reason: str = ""
    usage: TokenUsage | None = None

    def __post_init__(self) -> None:
        if self.tool_call_index is not None and self.tool_call_index < 0:
            raise ValueError("tool_call_index cannot be negative")


@dataclass
class _ToolCallBuffer:
    """Mutable internal buffer for one indexed streamed tool call."""

    id: str = ""
    name: str = ""
    raw_arguments: str = ""


@dataclass
class ModelStreamAccumulator:
    """Accumulate normalized deltas into one guarded ``ModelResponse``.

    Tool calls are bucketed by provider-supplied index, because IDs and names
    can arrive in an earlier fragment than their argument JSON.  The final
    response preserves index order and records malformed/incomplete JSON as a
    parse error instead of silently turning it into an empty argument mapping.
    """

    _content: list[str] = field(default_factory=list, init=False, repr=False)
    _tool_calls: dict[int, _ToolCallBuffer] = field(default_factory=dict, init=False, repr=False)
    _finish_reason: str = field(default="", init=False, repr=False)
    _usage: TokenUsage = field(default_factory=TokenUsage, init=False, repr=False)
    _deltas: list[ModelStreamDelta] = field(default_factory=list, init=False, repr=False)

    @property
    def content(self) -> str:
        return "".join(self._content)

    @property
    def deltas(self) -> tuple[ModelStreamDelta, ...]:
        """Return an immutable copy useful for diagnostics and tests."""
        return tuple(self._deltas)

    def add(self, delta: ModelStreamDelta) -> None:
        """Consume one normalized delta."""
        if not isinstance(delta, ModelStreamDelta):
            raise TypeError("ModelStreamAccumulator accepts ModelStreamDelta values only")
        self._deltas.append(delta)
        if delta.text:
            self._content.append(delta.text)
        if delta.tool_call_index is not None:
            call = self._tool_calls.setdefault(delta.tool_call_index, _ToolCallBuffer())
            if delta.tool_call_id:
                call.id = delta.tool_call_id
            if delta.tool_name:
                call.name = delta.tool_name
            if delta.arguments_delta:
                call.raw_arguments += delta.arguments_delta
        if delta.finish_reason:
            self._finish_reason = delta.finish_reason
        if delta.usage is not None:
            self._usage = TokenUsage(
                input_tokens=delta.usage.input_tokens,
                output_tokens=delta.usage.output_tokens,
            )

    def finish(self, *, raw: Any = None) -> ModelResponse:
        """Build the durable normalized response without mutating the buffers."""
        tool_calls: list[ToolCall] = []
        for index in sorted(self._tool_calls):
            call = self._tool_calls[index]
            raw_arguments = call.raw_arguments
            arguments: dict[str, Any] = {}
            parse_error: str | None = None
            if raw_arguments:
                try:
                    parsed = json.loads(raw_arguments)
                    if not isinstance(parsed, dict):
                        raise ValueError("tool arguments must decode to an object")
                    arguments = parsed
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    parse_error = str(exc)
            tool_calls.append(ToolCall(
                id=call.id,
                name=call.name,
                arguments=arguments,
                raw_arguments=raw_arguments,
                arguments_parse_error=parse_error,
            ))
        return ModelResponse(
            content=self.content,
            tool_calls=tool_calls,
            finish_reason=self._finish_reason,
            usage=TokenUsage(
                input_tokens=self._usage.input_tokens,
                output_tokens=self._usage.output_tokens,
            ),
            raw=raw,
        )

    def snapshot(self) -> MappingProxyType:
        """Return a small immutable diagnostic snapshot of accumulation state."""
        return MappingProxyType({
            "content": self.content,
            "tool_calls": len(self._tool_calls),
            "finish_reason": self._finish_reason,
            "input_tokens": self._usage.input_tokens,
            "output_tokens": self._usage.output_tokens,
        })


__all__ = ["ModelStreamAccumulator", "ModelStreamDelta"]
