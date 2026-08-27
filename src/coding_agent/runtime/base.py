"""Runtime 抽象基类。

Runtime 是 Tool 与真实 OS 之间的边界。
抽象后可以从 LocalRuntime 切换到 DockerRuntime 而不改 AgentLoop 与 Tool API。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RuntimeResult:
    """Runtime 执行结果。"""

    exit_code: int
    stdout: str
    stderr: str
    duration: float
    truncated: bool = False

    @property
    def combined_output(self) -> str:
        if self.stderr and self.stdout:
            return f"[stdout]\n{self.stdout}\n\n[stderr]\n{self.stderr}"
        return self.stdout or self.stderr or "(no output)"


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
    ) -> RuntimeResult:
        """执行命令。

        Args:
            command: shell 命令
            cwd: 工作目录（必须已 resolve 到合法位置）
            timeout: 超时秒数
            env: 额外环境变量
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