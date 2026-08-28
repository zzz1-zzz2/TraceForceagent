"""Textual TUI 应用（ClaudeCode 风格）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Header, Input, RichLog, Static

from coding_agent import __version__


class CodingAgentApp(App):
    """TraceForce Agent TUI — ClaudeCode 风格深色主题。"""

    CSS_PATH = "tui.css"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
    ]

    TITLE = "TraceForce Agent"
    SUB_TITLE = f"v{__version__}"

    # Chat 模式启发式：短任务、无 coding 信号 → 走纯 LLM 对话
    _CODING_SIGNALS = (
        ".py", ".js", ".ts", ".html", ".css", ".md", ".json", ".yaml", ".toml",
        "create", "write", "fix", "build", "refactor", "implement",
        "file", "function", "class ", "def ", "import ", "from ",
        "add ", "delete", "modify", "update ", "test ", "pytest",
        "git ", "commit", "branch", "merge", "deploy",
    )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(
            id="output",
            wrap=True,
            markup=True,
            highlight=True,
            max_lines=5000,
        )
        with Horizontal(id="footer_bar"):
            yield Static("Enter to submit · Ctrl+L clear · Ctrl+C quit", id="hints")
            yield Static("", id="stats")
        yield Input(
            placeholder="Try 'build a personal portfolio website'...",
            id="input",
        )

    # ---------- 输入事件 ----------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """用户按 Enter 提交任务。"""
        task = event.value.strip()
        if not task:
            return
        event.input.value = ""

        output = self.query_one("#output", RichLog)
        output.write(f"[user_prompt]> {task}[/user_prompt]\n\n")

        await self.run_agent(task)

    # ---------- agent 运行 ----------

    async def run_agent(self, task: str) -> None:
        """根据 task 启发式判断走 chat 还是 agent 模式。"""
        output = self.query_one("#output", RichLog)
        stats = self.query_one("#stats", Static)
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = True
        stats.update("[spinner]✻ working...[/spinner]")

        try:
            from coding_agent.config import load_config
            from coding_agent.model.client import ModelClient

            config = load_config()
            config.workspace_root = Path.cwd() / "workspace"

            task_lower = task.lower()
            looks_like_chat = (
                len(task) < 60
                and not any(sig in task_lower for sig in self._CODING_SIGNALS)
            )

            loop = asyncio.get_running_loop()

            if looks_like_chat:
                # ---- Chat 模式 ----
                client = ModelClient.from_config(config)
                reply = await loop.run_in_executor(
                    None,
                    lambda: client.chat(
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "你是 TraceForce Agent，一个用于软件工程任务的 coding agent。"
                                    "但当前用户只是想闲聊，请用 1-3 句话自然回复，"
                                    "不要假装在执行 coding 任务，也不要调用任何工具。"
                                ),
                            },
                            {"role": "user", "content": task},
                        ],
                        max_tokens=300,
                    ),
                )
                output.write(f"[agent_reply]✻[/agent_reply] {reply.strip()}\n\n")
                stats.update("[dim_meta]ready[/dim_meta]")
                return

            # ---- Coding Agent 模式 ----
            from coding_agent.agent.loop import run as agent_run

            result = await loop.run_in_executor(
                None,
                lambda: agent_run(
                    task=task,
                    workspace=config.workspace_root,
                    config=config,
                ),
            )

            output.write(
                f"[success]✓ {result.summary}[/success]\n"
            )
            output.write(
                f"[dim_meta]  {result.steps} steps · "
                f"{result.total_tokens:,} tokens · "
                f"stop: {result.stop_reason}[/dim_meta]\n\n"
            )
            stats.update(
                f"[dim_meta]{result.steps} steps · {result.total_tokens:,} tokens[/dim_meta]"
            )
        except Exception as e:
            output.write(f"[error]✗ Error: {e}[/error]\n\n")
            stats.update("[error]error[/error]")
        finally:
            input_widget.disabled = False
            input_widget.focus()

    # ---------- actions ----------

    def action_clear_log(self) -> None:
        """清空日志。"""
        self.query_one("#output", RichLog).clear()