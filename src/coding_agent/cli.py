"""CLI 入口（Typer）。

支持的命令：
  - python -m coding_agent --task "..." --workspace ./repo
  - python -m coding_agent --task-file task.md --workspace ./repo
  - python -m coding_agent --tui
  - python -m coding_agent --help
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console

from coding_agent import __version__

app = typer.Typer(
    name="coding-agent",
    help="Lightweight single-agent coding agent",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"coding-agent [bold cyan]{__version__}[/bold cyan]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="显示版本",
    ),
) -> None:
    """Coding Agent CLI 入口。"""


@app.command()
def run(
    task: str = typer.Option(None, "--task", "-t", help="任务描述字符串"),
    task_file: Path = typer.Option(
        None, "--task-file", "-f", help="从文件加载任务描述"
    ),
    workspace: Path = typer.Option(
        "./workspace", "--workspace", "-w", help="工作区目录"
    ),
    model: str = typer.Option(None, "--model", "-m", help="覆盖模型名"),
    max_steps: int = typer.Option(None, "--max-steps", help="覆盖最大步数"),
    benchmark: bool = typer.Option(False, "--benchmark", help="Benchmark 模式（禁止交互）"),
) -> None:
    """运行 Agent 完成一个编程任务。"""
    # 加载配置
    from coding_agent.config import AgentConfig, load_config

    config = load_config()
    if model:
        config.active_model = model
    if max_steps:
        config.max_steps = max_steps
    if benchmark:
        config.benchmark_mode = True

    # 解析任务
    if task_file:
        task_text = task_file.read_text(encoding="utf-8")
    elif task:
        task_text = task
    else:
        console.print("[red]必须提供 --task 或 --task-file[/red]")
        raise typer.Exit(1)

    # 准备 workspace
    workspace.mkdir(parents=True, exist_ok=True)
    config.workspace_root = workspace.resolve()

    # Fallback：pydantic-settings 不会自动把 DEEPSEEK_API_KEY 映射到 api_key 字段
    # 这里与 ModelClient.from_config 保持一致，从常见 env var 读取
    if not config.api_key:
        import os as _os
        config.api_key = (
            _os.environ.get("DEEPSEEK_API_KEY")
            or _os.environ.get("OPENAI_API_KEY")
            or _os.environ.get("GLM_API_KEY")
            or _os.environ.get("QWEN_API_KEY")
            or _os.environ.get("KIMI_API_KEY")
            or ""
        )

    if not config.api_key:
        console.print("[red]未配置 API key，请设置 .env 中的 DEEPSEEK_API_KEY 或 export DEEPSEEK_API_KEY=xxx[/red]")
        raise typer.Exit(1)

    # 运行
    from coding_agent.agent.loop import run as agent_run

    try:
        result = agent_run(task=task_text, workspace=config.workspace_root, config=config)
        console.print(f"\n[green]✓ 完成：[/green] {result.summary}")
        console.print(f"[dim]Stop reason: {result.stop_reason}[/dim]")
        console.print(f"[dim]Steps: {result.steps}, Tokens: {result.total_tokens}[/dim]")
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]错误：{e}[/red]")
        raise typer.Exit(1)


@app.command()
def tui(
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Agent 工作目录（默认 ./workspace）",
    ),
) -> None:
    """启动 Textual TUI。"""
    from coding_agent.tui.app import CodingAgentApp

    CodingAgentApp(workspace=workspace).run()


@app.command()
def check() -> None:
    """检查环境配置（API key、依赖）。"""
    from coding_agent.config import load_config

    config = load_config()
    if config.api_key:
        console.print(f"[green]✓[/green] API key 已配置（{config.api_key[:6]}...）")
    else:
        console.print("[red]✗[/red] API key 未配置")

    import shutil

    if shutil.which("rg"):
        console.print("[green]✓[/green] ripgrep 已安装")
    else:
        console.print("[red]✗[/red] ripgrep 未安装（sudo apt install ripgrep）")

    if shutil.which("git"):
        console.print("[green]✓[/green] git 已安装")
    else:
        console.print("[red]✗[/red] git 未安装")


if __name__ == "__main__":
    app()