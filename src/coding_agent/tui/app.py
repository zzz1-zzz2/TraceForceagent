"""Textual TUI 应用（ClaudeCode 风格）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Header, Input, RichLog, Static

from coding_agent import __version__
from coding_agent.events import (
    FeedbackRecorded,
    FinishAccepted,
    ModelCompleted,
    ModelFailed,
    ModelStarted,
    RunFailed,
    RunFinished,
    RunStarted,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
    TurnEnded,
    TurnStarted,
    ValidationCompleted,
)
from coding_agent.tui.bridge import AgentWorker, AgentWorkerError, AgentWorkerResult, UiAgentEvent
from coding_agent.tui.routing import CommandKind, route_input
from coding_agent.tui.state import RunUiState, initial_ui_state, reduce_event


class CodingAgentApp(App):
    """TraceForce Agent TUI — ClaudeCode 风格深色主题。

    输入约定：
    - 普通文本 → 走 Agent（工具调用完整循环）
    - `/chat <msg>` → 多轮对话（无工具）
    - `/workspace <path>` → 切换工作目录
    - `/clear` → 清屏
    """

    CSS_PATH = "tui.css"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
    ]

    TITLE = "TraceForce Agent"
    SUB_TITLE = f"v{__version__}"

    def __init__(self, workspace: Path | None = None) -> None:
        super().__init__()
        self._workspace: Path = (workspace or Path.cwd() / "workspace").resolve()
        self._chat_history: list[dict] = []  # 多轮 chat 历史
        self._ui_state: RunUiState = initial_ui_state()
        self._worker: AgentWorker | None = None
        self._chat_system: str = (
            "你是 TraceForce Agent，一个软件工程任务的 coding agent。"
            "当前用户选择走纯对话模式（不带工具）。请用简洁中文回复，"
            "但若用户提到具体工程任务，仍应说明自己无法执行需要工具的操作。"
        )

    # ---------- 布局 ----------

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
            yield Static(
                "Enter submit · /chat msg · /workspace path · /clear · Ctrl+C quit",
                id="hints",
            )
            yield Static("", id="stats")
        yield Input(
            placeholder="Try 'build a personal portfolio website' or '/chat hi'",
            id="input",
        )

    def on_mount(self) -> None:
        """启动时显示当前 workspace。"""
        output = self.query_one("#output", RichLog)
        output.write(
            f"[dim_meta]workspace: {self._workspace}[/dim_meta]\n"
            f"[dim_meta]提示：默认进入 Agent 模式；输入 /chat <msg> 走纯对话；/workspace <path> 切换；/clear 清屏。[/dim_meta]\n\n"
        )

    # ---------- 输入事件 ----------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """用户按 Enter 提交任务或命令。先解析路由再分派。"""
        raw = event.value.strip()
        event.input.value = ""

        output = self.query_one("#output", RichLog)
        route = route_input(raw)

        if route.kind is CommandKind.CLEAR:
            output.clear()
            self._chat_history.clear()  # 顺手清掉 chat 历史
            return

        if route.kind is CommandKind.WORKSPACE:
            if not route.payload:
                output.write("[error]用法：/workspace <path>[/error]\n\n")
                return
            new_path = Path(route.payload).expanduser().resolve()
            try:
                new_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                output.write(f"[error]无法创建目录 {new_path}: {e}[/error]\n\n")
                return
            self._workspace = new_path
            output.write(f"[success]✓ workspace 已切换到 {self._workspace}[/success]\n\n")
            return

        if route.kind is CommandKind.UNKNOWN:
            output.write(f"[error]未知命令：{route.payload}[/error]\n\n")
            return

        if route.kind is CommandKind.CHAT:
            if not route.payload:
                output.write("[error]用法：/chat <你的消息>[/error]\n\n")
                return
            output.write(f"[user_prompt]> {route.payload}[/user_prompt]\n\n")
            await self.run_chat(route.payload)
            return

        # 默认 AGENT
        if not route.payload:
            return
        output.write(f"[user_prompt]> {route.payload}[/user_prompt]\n\n")
        await self.run_agent(route.payload)

    # ---------- Agent 模式 ----------

    async def run_agent(self, task: str) -> None:
        """Start the AgentLoop worker; lifecycle messages drive the UI."""
        if self._worker is not None and self._worker.is_alive:
            return

        from coding_agent.config import load_config

        config = load_config()
        config.workspace_root = self._workspace
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = True
        self._ui_state = initial_ui_state()
        self._worker = AgentWorker(
            self,
            task=task,
            workspace=config.workspace_root,
            config=config,
        )
        self._worker.start()
        self.query_one("#stats", Static).update("[spinner]✻ working...[/spinner]")

    def on_ui_agent_event(self, message: UiAgentEvent) -> None:
        """Reduce one worker event on Textual's application thread."""
        event = message.event
        previous = self._ui_state
        self._ui_state = reduce_event(previous, event)
        if self._ui_state is previous:
            return
        self._render_agent_event(event)
        self._render_stats()

    def on_agent_worker_result(self, message: AgentWorkerResult) -> None:
        """Keep the result as a fallback for adapters without terminal events."""
        if not self._ui_state.terminal:
            self.query_one("#stats", Static).update(
                f"[dim_meta]{message.result.steps} steps · "
                f"{message.result.total_tokens:,} tokens[/dim_meta]"
            )
        self._finish_agent_input()

    def on_agent_worker_error(self, message: AgentWorkerError) -> None:
        """Surface an uncaught worker error without duplicating RunFailed."""
        if not self._ui_state.terminal:
            output = self.query_one("#output", RichLog)
            output.write(f"[error]✗ Error: {escape(str(message.error))}[/error]\n\n")
            self.query_one("#stats", Static).update("[error]error[/error]")
        self._finish_agent_input()

    def _render_agent_event(self, event: object) -> None:
        """Render compact lifecycle text; widgets remain a later P2-1C card."""
        output = self.query_one("#output", RichLog)
        if isinstance(event, RunStarted):
            output.write("[dim_meta]⏺ run started[/dim_meta]")
        elif isinstance(event, TurnStarted):
            output.write(f"[spinner]✻ turn {event.turn} · thinking[/spinner]")
        elif isinstance(event, ModelStarted):
            self.query_one("#stats", Static).update(
                f"[spinner]✻ {escape(event.model or 'model')} · step {event.step}[/spinner]"
            )
        elif isinstance(event, ModelCompleted):
            if event.response is not None and event.response.content.strip():
                output.write(f"[agent_reply]{escape(event.response.content)}[/agent_reply]")
        elif isinstance(event, ModelFailed):
            output.write(f"[error]✗ model: {escape(event.error or event.error_type)}[/error]")
        elif isinstance(event, ToolStarted):
            output.write(f"[tool_call]● {escape(event.tool_name)}[/tool_call]")
        elif isinstance(event, (ToolCompleted, ToolFailed)):
            tool = (self._ui_state.tools or {}).get((event.run_id, event.action_id))
            status = tool.status.value if tool is not None else "error"
            summary = tool.summary if tool is not None else ""
            output.write(f"[tool_output]⎿ {status}: {escape(summary or event.event_type)}[/tool_output]")
        elif isinstance(event, ValidationCompleted):
            label = "passed" if event.passed else "failed"
            output.write(f"[{'success' if event.passed else 'error'}]validation {label}: "
                         f"{escape(event.summary)}[/{'success' if event.passed else 'error'}]")
        elif isinstance(event, FeedbackRecorded):
            output.write(f"[dim_meta]feedback: {escape(event.content)}[/dim_meta]")
        elif isinstance(event, FinishAccepted):
            output.write(f"[success]✓ {escape(event.summary)}[/success]")
        elif isinstance(event, RunFinished):
            output.write(
                f"[dim_meta]{self._ui_state.step} steps · "
                f"{self._ui_state.total_tokens:,} tokens · "
                f"stop: {escape(self._ui_state.terminal_reason or event.reason)}[/dim_meta]\n\n"
            )
            self._finish_agent_input()
        elif isinstance(event, TurnEnded):
            return
        elif isinstance(event, RunFailed):
            output.write(f"[error]✗ Error: {escape(event.error or event.error_type)}[/error]\n\n")
            self._finish_agent_input()

    def _render_stats(self) -> None:
        """Update the footer from reducer state, not from worker callbacks."""
        state = self._ui_state
        if state.terminal:
            label = "error" if state.phase == "error" else state.phase
            self.query_one("#stats", Static).update(
                f"[{'error' if state.phase == 'error' else 'dim_meta'}]"
                f"{state.step} steps · {state.total_tokens:,} tokens · {label}[/"
                f"{'error' if state.phase == 'error' else 'dim_meta'}]"
            )
        elif state.phase in {"thinking", "working", "validation", "feedback"}:
            self.query_one("#stats", Static).update(
                f"[spinner]✻ {state.phase} · step {state.step}[/spinner]"
            )

    def _finish_agent_input(self) -> None:
        """Re-enable input after terminal worker delivery."""
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = False
        input_widget.focus()

    # ---------- Chat 模式（多轮） ----------

    async def run_chat(self, user_msg: str) -> None:
        """多轮纯对话（保留 history）。"""
        output = self.query_one("#output", RichLog)
        stats = self.query_one("#stats", Static)
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = True
        stats.update("[spinner]✻ chat...[/spinner]")

        try:
            from coding_agent.config import load_config
            from coding_agent.model.client import ModelClient

            config = load_config()
            client = ModelClient.from_config(config)

            # 把当前 user msg 加进去，传全部消息给 LLM（这是真正的连续对话）
            self._chat_history.append({"role": "user", "content": user_msg})

            messages: list[dict] = [{"role": "system", "content": self._chat_system}] + \
                                   list(self._chat_history)

            loop = asyncio.get_running_loop()
            reply = await loop.run_in_executor(
                None,
                lambda: client.chat(messages=messages, max_tokens=500),
            )

            # 把 reply 也加进 history，下次接着对话
            self._chat_history.append({"role": "assistant", "content": reply.strip()})

            output.write(f"[agent_reply]✻[/agent_reply] {reply.strip()}\n\n")
            stats.update(
                f"[dim_meta]chat · {len(self._chat_history) // 2} turns[/dim_meta]"
            )
        except Exception as e:
            output.write(f"[error]✗ Error: {e}[/error]\n\n")
            stats.update("[error]error[/error]")
        finally:
            input_widget.disabled = False
            input_widget.focus()

    # ---------- actions ----------

    def action_clear_log(self) -> None:
        """清空日志（Ctrl+L）。"""
        self.query_one("#output", RichLog).clear()
