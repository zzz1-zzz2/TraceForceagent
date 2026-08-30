"""Runtime 抽象基类。

Runtime 是 Tool 与真实 OS 之间的边界。
抽象后可以从 LocalRuntime 切换到 DockerRuntime 而不改 AgentLoop 与 Tool API。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RuntimeResult:
    """Runtime 执行结果。"""

    exit_code: int
    stdout: str
    stderr: str
    duration: float
    truncated: bool = False
    cancelled: bool = False
    timed_out: bool = False

    @property
    def combined_output(self) -> str:
        if self.stderr and self.stdout:
            return f"[stdout]\n{self.stdout}\n\n[stderr]\n{self.stderr}"
        return self.stdout or self.stderr or "(no output)"


@dataclass(frozen=True, kw_only=True)
class RuntimeOutputChunk:
    """One bounded chunk of tool output emitted while a Runtime is streaming.

    The chunk carries only the new fragment plus its position in the stream.
    Runtime implementations must never deduplicate or coalesce fragments:
    the reducer and TUI rely on raw sequential delivery.
    """

    text: str
    chunk_index: int
    stream: str = "combined"


ToolOutputSink = Callable[[RuntimeOutputChunk], None]


@dataclass(frozen=True, kw_only=True)
class ToolExecutionContext:
    """Pure execution context threaded into Runtime.execute().

    The Runtime contract is intentionally narrow: it receives a cancellation
    token and an optional output sink, and emits raw ``RuntimeOutputChunk``
    callbacks without depending on AgentEvent / EventEmitter. The AgentLoop
    owns the conversion from RuntimeOutputChunk to ``ToolOutputDelta`` so the
    dependency direction stays Runtime → Loop → Observers.
    """

    cancellation_token: object | None = None
    on_output: ToolOutputSink | None = None


class Runtime(ABC):
    """Runtime 抽象基类。"""

    workspace: Path

    @abstractmethod
    def execute(
        self,
        command: str,
        cwd: Path,
        timeout: int = 60,
        env: dict | None = None,
        context: ToolExecutionContext | None = None,
    ) -> RuntimeResult:
        """执行命令。

        Args:
            command: shell 命令
            cwd: 工作目录（必须已 resolve 到合法位置）
            timeout: 超时秒数
            env: 额外环境变量
            context: 可选执行上下文（取消 + 流式回调）
        """
        raise NotImplementedError


def _truncate(text: str, max_bytes: int) -> tuple[str, bool]:
    """按字节截断文本，返回 (text, truncated)。"""
    if len(text.encode("utf-8")) <= max_bytes:
        return text, False
    encoded = text.encode("utf-8")[:max_bytes]
    # 避免切断多字节字符
    while encoded and (encoded[-1] & 0xC0) == 0x80:
        encoded = encoded[:-1]
    return encoded.decode("utf-8", errors="ignore") + "\n... (truncated)", True


__all__ = [
    "Runtime",
    "RuntimeResult",
    "RuntimeOutputChunk",
    "ToolExecutionContext",
    "ToolOutputSink",
]


@dataclass
class _StreamingBuffer:
    """Buffer that accumulates streamed RuntimeOutputChunk fragments.

    Holds both the raw text (for the durable ``ToolResult.content``) and a
    bounded preview used by the TUI widget. ``max_chars`` is applied to the
    raw text so the durable record is always bounded regardless of how much
    data the Runtime emitted.
    """

    max_chars: int = 200_000
    parts: list[str] = field(default_factory=list)
    length: int = 0
    truncated: bool = False

    def append(self, text: str) -> None:
        if not text:
            return
        if self.max_chars <= 0:
            self.truncated = True
            self.parts.clear()
            self.length = 0
            return
        if len(text) > self.max_chars:
            self.parts = [text[-self.max_chars:]]
            self.length = self.max_chars
            self.truncated = True
            return
        self.parts.append(text)
        self.length += len(text)
        if self.length > self.max_chars:
            overflow = self.length - self.max_chars
            while overflow and self.parts:
                head = self.parts[0]
                if len(head) <= overflow:
                    self.parts.pop(0)
                    self.length -= len(head)
                    overflow -= len(head)
                else:
                    self.parts[0] = head[overflow:]
                    self.length -= overflow
                    overflow = 0
            self.truncated = True

    def render(self) -> str:
        return "".join(self.parts)
