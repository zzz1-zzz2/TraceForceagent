"""LocalRuntime：本地 subprocess 执行。

设计要点：
- 每次命令独立 subprocess（无 persistent shell）
- 路径必须在 workspace 内
- timeout 默认 60s
- 输出超过 max_tool_output 截断
- 使用 Popen 流式读取，stdout/stderr 合并为一个 stream
- 使用 start_new_session 隔离进程组，便于按组取消/超时终止
- 通过 ToolExecutionContext 暴露 RuntimeOutputChunk，AgentLoop 负责
  转换成 ToolOutputDelta，避免 Runtime 直接依赖 AgentEvent/EventEmitter
"""

from __future__ import annotations

import codecs
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from coding_agent.config import AgentConfig
from coding_agent.runtime.base import (
    Runtime,
    RuntimeOutputChunk,
    RuntimeResult,
    ToolExecutionContext,
    _StreamingBuffer,
)


class _TokenCancelled(RuntimeError):
    """Raised internally when a cancellation token trips mid-execution."""


class LocalRuntime(Runtime):
    """本地 Runtime 实现。"""

    def __init__(self, workspace: Path, config: AgentConfig):
        self.workspace = workspace.resolve()
        self.config = config
        self.max_output = config.max_tool_output
        self.default_timeout = config.command_timeout

    def execute(
        self,
        command: str,
        cwd: Path,
        timeout: int = 60,
        env: dict | None = None,
        context: ToolExecutionContext | None = None,
    ) -> RuntimeResult:
        """执行 shell 命令。

        失败模式：
        - subprocess.TimeoutExpired: 返回 exit_code=-1，cancelled=False
        - 取消：返回 exit_code=-1，cancelled=True
        - FileNotFoundError: 命令不存在
        - 其他异常: 抛出

        流式语义：
        - 每个 read chunk 通过 ``context.on_output`` 回调一次；
        - 不去重、不合并；调用方按收到顺序累计。
        """
        full_env = None
        if env:
            full_env = {**os.environ, **env}

        start = time.time()
        sink = context.on_output if context is not None else None
        token = context.cancellation_token if context is not None else None
        buffer = _StreamingBuffer(max_chars=self.max_output)
        stream_offset = 0

        def emit(text: str) -> None:
            nonlocal stream_offset
            if not text:
                return
            stream_offset_start = stream_offset
            stream_offset += len(text)
            buffer.append(text)
            if sink is None:
                return
            chunk = RuntimeOutputChunk(text=text, chunk_index=stream_offset_start)
            try:
                output_sink = sink
                if output_sink is not None:
                    output_sink(chunk)
            except Exception:
                # Streaming is best-effort: an observer failure must not crash
                # the running subprocess.
                pass

        proc: subprocess.Popen[bytes] | None = None
        stdout_thread: threading.Thread | None = None
        stderr_thread: threading.Thread | None = None
        watcher: threading.Thread | None = None
        cancel_flag = threading.Event()
        process_done = threading.Event()

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                env=full_env,
                executable="/bin/bash",
                start_new_session=True,
                bufsize=0,
            )

            assert proc.stdout is not None

            def _drain() -> None:
                assert proc is not None and proc.stdout is not None
                decoder = codecs.getincrementaldecoder("utf-8")()
                output_fd = proc.stdout.fileno()
                while True:
                    chunk = os.read(output_fd, 4096)
                    if not chunk:
                        remainder = decoder.decode(b"", final=True)
                        if remainder:
                            emit(remainder)
                        return
                    text = decoder.decode(chunk)
                    if text:
                        emit(text)
                    if token is not None and getattr(token, "is_cancelled", False):
                        cancel_flag.set()
                        # Terminate proactively so the main thread's
                        # ``proc.wait`` returns promptly even when the child
                        # never produces more output (e.g. ``sleep N``).
                        self._terminate_process_group(proc, grace=0.5)
                        return

            stdout_thread = threading.Thread(
                target=_drain, name="traceforce-runtime-drain", daemon=True
            )
            stdout_thread.start()
            stderr_thread = None  # stdout/stderr 已合并

            # Cancellation watcher: when the token trips, kill the whole
            # process group so even output-silent commands exit quickly.
            if token is not None:

                def _watch() -> None:
                    while not process_done.wait(0.05):
                        if not getattr(token, "is_cancelled", False):
                            continue
                        cancel_flag.set()
                        self._terminate_process_group(proc, grace=0.5)
                        return

                watcher = threading.Thread(
                    target=_watch, name="traceforce-runtime-cancel", daemon=True
                )
                watcher.start()

            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._terminate_process_group(proc, grace=0.5)
                process_done.set()
                if stdout_thread is not None:
                    stdout_thread.join(timeout=1.0)
                if watcher is not None:
                    watcher.join(timeout=0.5)
                duration = time.time() - start
                return RuntimeResult(
                    exit_code=-1,
                    stdout=buffer.render(),
                    stderr=f"Command timeout after {timeout}s",
                    duration=duration,
                    truncated=buffer.truncated,
                    cancelled=False,
                    timed_out=True,
                )

            process_done.set()
            if stdout_thread is not None:
                stdout_thread.join(timeout=2.0)
            if watcher is not None:
                watcher.join(timeout=0.5)
            if cancel_flag.is_set():
                duration = time.time() - start
                return RuntimeResult(
                    exit_code=-1,
                    stdout=buffer.render(),
                    stderr="Command cancelled",
                    duration=duration,
                    truncated=buffer.truncated,
                    cancelled=True,
                )

            duration = time.time() - start
            return RuntimeResult(
                exit_code=rc,
                stdout=buffer.render(),
                stderr="",
                duration=duration,
                truncated=buffer.truncated,
                cancelled=False,
            )

        except FileNotFoundError as e:
            duration = time.time() - start
            return RuntimeResult(
                exit_code=127,
                stdout="",
                stderr=f"Shell not found: {e}",
                duration=duration,
            )
        finally:
            if proc is not None and proc.poll() is None:
                self._terminate_process_group(proc, grace=0.0)
            if stdout_thread is not None and stdout_thread.is_alive():
                stdout_thread.join(timeout=0.5)
            if stderr_thread is not None and stderr_thread.is_alive():
                stderr_thread.join(timeout=0.5)
            process_done.set()
            if watcher is not None and watcher.is_alive():
                watcher.join(timeout=0.5)

    @staticmethod
    def _terminate_process_group(proc: subprocess.Popen[bytes], *, grace: float) -> None:
        """Terminate the whole process group, escalating to SIGKILL after ``grace`` seconds."""
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception:
            try:
                proc.terminate()
            except Exception:
                return
        if grace <= 0:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    return
            return
        deadline = time.time() + grace
        while time.time() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.05)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except Exception:
            try:
                proc.kill()
            except Exception:
                return

    def write_file(self, path: Path, content: str) -> None:
        """工具方法：原子写文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
