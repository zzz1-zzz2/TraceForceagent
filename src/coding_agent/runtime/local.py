"""LocalRuntime：本地 subprocess 执行。

设计要点：
- 每次命令独立 subprocess（无 persistent shell）
- 路径必须在 workspace 内
- timeout 默认 60s
- 输出超过 max_tool_output 截断
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from coding_agent.config import AgentConfig
from coding_agent.runtime.base import Runtime, RuntimeResult, _truncate


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
    ) -> RuntimeResult:
        """执行 shell 命令。

        失败模式：
        - subprocess.TimeoutExpired: 返回 exit_code=-1
        - FileNotFoundError: 命令不存在
        - 其他异常: 抛出
        """
        # 合并环境变量
        full_env = None
        if env:
            import os
            full_env = {**os.environ, **env}

        start = time.time()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=full_env,
                executable="/bin/bash",
            )
            duration = time.time() - start

            stdout, out_truncated = _truncate(proc.stdout or "", self.max_output)
            stderr, err_truncated = _truncate(proc.stderr or "", self.max_output)

            return RuntimeResult(
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration=duration,
                truncated=out_truncated or err_truncated,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start
            # 尝试 kill 子进程（subprocess.run 在 timeout 时应该已经做了）
            return RuntimeResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timeout after {timeout}s",
                duration=duration,
                truncated=False,
            )

        except FileNotFoundError as e:
            # shell=True 时，命令不存在会通过 returncode != 0 返回
            # 这里捕获的是 python 找不到（如 /bin/sh 不存在）
            return RuntimeResult(
                exit_code=127,
                stdout="",
                stderr=f"Shell not found: {e}",
                duration=time.time() - start,
            )

    def write_file(self, path: Path, content: str) -> None:
        """工具方法：原子写文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
