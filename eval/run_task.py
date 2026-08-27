"""评测脚本入口。

用法：
  python -m eval.run_task --task eval/tasks/A_safe_divide --model deepseek-chat
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from coding_agent.config import AgentConfig, load_config
from coding_agent.agent.loop import run as agent_run


def copy_task_to_workspace(task_dir: Path, workspace: Path) -> None:
    """把 task 的 src/ 和 tests/ 复制到 workspace。"""
    src = task_dir / "src"
    tests = task_dir / "tests"

    if src.exists():
        shutil.copytree(src, workspace / "src", dirs_exist_ok=True)
    if tests.exists():
        shutil.copytree(tests, workspace / "tests", dirs_exist_ok=True)

    # 拷贝 task.md
    task_md = task_dir / "task.md"
    if task_md.exists():
        shutil.copy(task_md, workspace / "task.md")


def run_pytest(workspace: Path, timeout: int = 120) -> tuple[bool, str]:
    """在工作区跑 pytest。"""
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "-x", "--tb=short", "-q"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        passed = proc.returncode == 0
        output = proc.stdout + proc.stderr
        return passed, output
    except subprocess.TimeoutExpired:
        return False, "pytest timeout"
    except Exception as e:
        return False, f"pytest error: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agent on a single task")
    parser.add_argument("--task", required=True, help="Task directory (containing task.md, src/, tests/)")
    parser.add_argument("--model", default=None, help="Override model name")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    task_dir = Path(args.task).resolve()
    if not task_dir.exists():
        print(f"Task directory not found: {task_dir}")
        return 1

    task_md = task_dir / "task.md"
    if not task_md.exists():
        print(f"task.md not found in {task_dir}")
        return 1

    task_text = task_md.read_text(encoding="utf-8")

    # 准备 workspace
    workspace = Path(tempfile.mkdtemp(prefix="eval_"))
    copy_task_to_workspace(task_dir, workspace)

    # 配置
    config = load_config()
    if args.model:
        config.active_model = args.model
    config.max_steps = args.max_steps
    config.workspace_root = workspace

    if not args.quiet:
        print(f"=== Running task: {task_dir.name} ===")
        print(f"Workspace: {workspace}")
        print(f"Model: {config.active_model}")
        print()

    # 跑 Agent
    try:
        result = agent_run(task=task_text, workspace=workspace, config=config)
    except Exception as e:
        print(f"Agent error: {e}")
        return 2

    # 评测
    if not args.quiet:
        print(f"\n=== Agent finished ===")
        print(f"Summary: {result.summary}")
        print(f"Steps: {result.steps}, Tokens: {result.total_tokens}")

    passed, pytest_output = run_pytest(workspace)

    print(f"\n=== Result ===")
    print(f"Resolved: {passed}")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Steps: {result.steps}")
    print(f"Tokens: {result.total_tokens}")
    print(f"Duration: {result.duration:.1f}s")

    if not passed:
        print(f"\n--- pytest output ---")
        print(pytest_output[-2000:])  # last 2000 chars

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())