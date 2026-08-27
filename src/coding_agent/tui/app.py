"""Textual TUI 应用（ClaudeCode 风格）。"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from coding_agent import __version__


class CodingAgentApp(App):
    """Coding Agent TUI。"""

    CSS_PATH = "tui.css"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
    ]

    TITLE = "Coding Agent"
    SUB_TITLE = f"v{__version__}"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Status: ready", id="status")
        with Horizontal():
            with Vertical(id="left"):
                yield RichLog(id="output", wrap=True, markup=True, highlight=True)
            with Vertical(id="right", classes="sidebar"):
                yield Static("Plan", classes="sidebar-title")
                yield RichLog(id="plan_log", wrap=True)
        yield Input(placeholder="Enter your task...", id="input")
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """用户提交任务。"""
        task = event.value.strip()
        if not task:
            return
        event.input.value = ""

        output = self.query_one("#output", RichLog)
        output.write(f"[bold cyan]USER:[/bold cyan] {task}\n")

        await self.run_agent(task)

    async def run_agent(self, task: str) -> None:
        """实际运行 Agent。"""
        output = self.query_one("#output", RichLog)
        output.write("[dim]Running agent...[/dim]\n")

        try:
            from coding_agent.config import load_config
            from coding_agent.agent.loop import run as agent_run

            config = load_config()
            config.workspace_root = Path.cwd() / "workspace"

            result = agent_run(task=task, workspace=config.workspace_root, config=config)

            output.write(f"\n[bold green]✓ Finished:[/bold green] {result.summary}\n")
            output.write(f"[dim]Stop: {result.stop_reason} | Steps: {result.steps} | Tokens: {result.total_tokens}[/dim]\n")
        except Exception as e:
            output.write(f"[red]Error: {e}[/red]\n")

    def action_clear_log(self) -> None:
        """清空日志。"""
        self.query_one("#output", RichLog).clear()