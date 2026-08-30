"""git_diff 工具：查看当前工作区修改。

P1-2：现在同时返回
- staged (`git diff --staged`)
- unstaged (`git diff`)
- untracked files (`git status --porcelain`)

这三个一起是 model 看到"还剩什么没改"的完整视图。
"""

from __future__ import annotations

import subprocess

from coding_agent.model.types import ToolResult
from coding_agent.runtime.base import Runtime, ToolExecutionContext
from coding_agent.tools.base import Tool


class GitDiffTool(Tool):
    """查看 git diff（用于 finish 前自检）。

    输出结构：
        ## Staged changes (git diff --staged)
        <diff or "(none)">

        ## Unstaged changes (git diff)
        <diff or "(none)">

        ## Untracked files (git status --porcelain)
        <list of ?? file paths or "(none)">
    """

    name = "git_diff"
    description = (
        "Show current git diff in the workspace, including staged, unstaged, "
        "and untracked files. Use before finish() to verify all intended "
        "changes are present."
    )
    schema = {
        "type": "object",
        "properties": {
            "max_lines": {
                "type": "integer",
                "description": "Maximum diff lines per section (default 200)",
                "default": 200,
            },
        },
        "required": [],
    }

    def execute(self, args: dict, runtime: Runtime, context: ToolExecutionContext | None = None) -> ToolResult:
        max_lines = min(args.get("max_lines", 200), 2000)

        # 1) 先 detect 是不是 git repo。`git diff --staged` 在非 repo 时会被
        #    解释成 `git diff --no-index`（外部对比模式），错误信息误导。
        probe = self._run_git(["rev-parse", "--is-inside-work-tree"], runtime)
        if not probe.ok or probe.stdout.strip() != "true":
            return ToolResult.fail(
                "Workspace is not a git repository. git_diff requires `git init`.",
                is_runtime_error=True,
            )

        # 2) 三段独立调用，避免某个失败影响其他
        staged = self._run_git(["diff", "--staged", "--no-color"], runtime)
        unstaged = self._run_git(["diff", "--no-color"], runtime)
        untracked = self._run_git(["status", "--porcelain", "--untracked-files=all"], runtime)

        # 任一 command 失败（且 stderr 非空）→ 仍然汇总，让模型看到全貌
        sections: list[str] = []

        if not staged.ok:
            sections.append(f"## Staged changes\n[error] {staged.stderr}")
        else:
            sections.append(
                f"## Staged changes\n{staged.stdout or '(none)'}"
            )

        if not unstaged.ok:
            sections.append(f"## Unstaged changes\n[error] {unstaged.stderr}")
        else:
            sections.append(
                f"## Unstaged changes\n{unstaged.stdout or '(none)'}"
            )

        if not untracked.ok:
            sections.append(f"## Untracked files\n[error] {untracked.stderr}")
        else:
            # git status --porcelain 格式: "XY path"
            # 我们只关心 untracked: 行首以 "??" 开头
            untracked_paths = [
                line[3:].strip() for line in untracked.stdout.splitlines()
                if line.startswith("??")
            ]
            if untracked_paths:
                body = "\n".join(untracked_paths)
            else:
                body = "(none)"
            sections.append(f"## Untracked files\n{body}")

        full = "\n\n".join(sections)

        # 整体截断
        lines = full.splitlines()
        truncated = len(lines) > max_lines * 3  # 3 sections
        if truncated:
            body = "\n".join(lines[: max_lines * 3]) + \
                f"\n... ({len(lines) - max_lines * 3} more lines)"
        else:
            body = full

        any_error = not (staged.ok and unstaged.ok and untracked.ok)
        return ToolResult.ok(
            body,
            truncated=truncated,
            summary=("git diff (partial errors)" if any_error else "git diff"),
        )

    @staticmethod
    def _run_git(args: list[str], runtime: Runtime) -> "_GitRun":
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(runtime.workspace),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return _GitRun(ok=False, stdout="", stderr="git timeout")
        except FileNotFoundError:
            return _GitRun(ok=False, stdout="", stderr="git not installed")
        except Exception as e:
            return _GitRun(ok=False, stdout="", stderr=str(e))

        if proc.returncode != 0:
            return _GitRun(ok=False, stdout=proc.stdout, stderr=proc.stderr)
        return _GitRun(ok=True, stdout=proc.stdout, stderr=proc.stderr)


class _GitRun:
    """一次 git 子命令的结果（不抛异常）。"""

    __slots__ = ("ok", "stdout", "stderr")

    def __init__(self, ok: bool, stdout: str, stderr: str):
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr
