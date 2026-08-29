"""Textual TUI application backed by componentized lifecycle views."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.events import Key
from textual.widget import Widget
from textual.widgets import Input

from coding_agent import __version__
from coding_agent.config import load_config, run_preflight
from coding_agent.events import (
    AssistantReplied,
    FeedbackRecorded,
    FinishAccepted,
    ModelCompleted,
    ModelFailed,
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
from coding_agent.tui.widgets import (
    AssistantMessageWidget,
    BrandBarWidget,
    ComposerBarWidget,
    FinalResultWidget,
    FooterMetaWidget,
    NoticeWidget,
    RunStatusWidget,
    ToolExecutionWidget,
    TranscriptView,
    UserMessageWidget,
    ValidationWidget,
    WelcomeWidget,
)


class CodingAgentApp(App):
    """TraceForce TUI with a stable transcript and fixed status area."""

    CSS_PATH = "tui.css"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
        ("ctrl+o", "toggle_tools", "Expand/collapse tools"),
    ]

    TITLE = "TraceForce Agent"
    SUB_TITLE = f"v{__version__}"

    def __init__(self, workspace: Path | None = None) -> None:
        super().__init__()
        self._workspace: Path = (workspace or Path.cwd()).resolve()
        self._chat_history: list[dict[str, str]] = []
        self._ui_state: RunUiState = initial_ui_state()
        self._worker: AgentWorker | None = None
        self._welcome: WelcomeWidget | None = None
        self._assistant_widgets: dict[tuple[str, int], AssistantMessageWidget] = {}
        self._tool_widgets: dict[tuple[str, str], ToolExecutionWidget] = {}
        self._validation_widgets: dict[tuple[str, int], ValidationWidget] = {}
        self._notice_widgets: dict[tuple[str, int], NoticeWidget] = {}
        self._final_widgets: dict[str, FinalResultWidget] = {}
        self._chat_system = (
            "你是 TraceForce Agent，一个软件工程任务的 coding agent。"
            "当前用户选择走纯对话模式（不带工具）。请用简洁中文回复，"
            "但若用户提到具体工程任务，仍应说明自己无法执行需要工具的操作。"
        )

    def compose(self) -> ComposeResult:
        yield BrandBarWidget(self._workspace, id="brand_bar")
        yield TranscriptView(id="transcript")
        yield RunStatusWidget("ready", id="run_status")
        yield ComposerBarWidget(id="composer")
        yield FooterMetaWidget(self._workspace, id="footer_meta")

    async def on_mount(self) -> None:
        """Mount the initial welcome view after the app is ready."""
        self._welcome = WelcomeWidget(self._workspace, id="welcome")
        await self._transcript().append_entry(self._welcome)
        self._status().apply_state(self._ui_state)
        self._footer().apply_state(self._ui_state)
        await self._run_mount_preflight()
        self.query_one("#input", Input).focus()

    async def _run_mount_preflight(self) -> None:
        """Run a credentials-less preflight on mount and surface failures.

        We deliberately skip the credentials check on mount — most users
        open the TUI before typing a task. The hardened re-check lives in
        :meth:`run_agent`.
        """
        try:
            config = load_config()
        except Exception as exc:  # noqa: BLE001 - surface redacted message
            await self._append(
                NoticeWidget(f"config load failed: {exc}", level="error")
            )
            return
        result = run_preflight(
            config,
            workspace=self._workspace,
            require_credentials=False,
        )
        if not result.ok:
            names = ", ".join(result.failing_names())
            await self._append(
                NoticeWidget(
                    f"preflight failed: {names} — see `coding-agent check`",
                    level="system",
                )
            )

    def _transcript(self) -> TranscriptView:
        return self.query_one("#transcript", TranscriptView)

    def _status(self) -> RunStatusWidget:
        return self.query_one("#run_status", RunStatusWidget)

    def _footer(self) -> FooterMetaWidget:
        return self.query_one("#footer_meta", FooterMetaWidget)

    async def _append(self, widget: Widget) -> None:
        """Mount one transcript widget through the single transcript owner."""
        await self._transcript().append_entry(widget)

    async def _hide_welcome(self) -> None:
        if self._welcome is not None and self._welcome.is_attached:
            await self._welcome.remove()
        self._welcome = None

    async def _reset_transcript(self) -> None:
        await self._transcript().clear_entries()
        self._assistant_widgets.clear()
        self._tool_widgets.clear()
        self._validation_widgets.clear()
        self._notice_widgets.clear()
        self._final_widgets.clear()
        self._welcome = WelcomeWidget(self._workspace, id="welcome")
        await self._append(self._welcome)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Route a submitted line to a command, chat request, or Agent run."""
        raw = event.value.strip()
        event.input.value = ""
        route = route_input(raw)

        if route.kind is CommandKind.CLEAR:
            self._chat_history.clear()
            await self._reset_transcript()
            self._ui_state = initial_ui_state()
            self._status().apply_state(self._ui_state)
            self._footer().apply_state(self._ui_state)
            return

        if route.kind is CommandKind.WORKSPACE:
            if not route.payload:
                await self._append(NoticeWidget("用法：/workspace <path>", level="error"))
                return
            new_path = Path(route.payload).expanduser().resolve()
            try:
                new_path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                await self._append(NoticeWidget(f"无法创建目录 {new_path}: {exc}", level="error"))
                return
            self._workspace = new_path
            self.query_one(BrandBarWidget).set_workspace(new_path)
            self._footer().set_workspace(new_path)
            if self._welcome is not None:
                self._welcome.set_workspace(new_path)
            await self._append(NoticeWidget(f"workspace 已切换到 {new_path}", level="system"))
            return

        if route.kind is CommandKind.UNKNOWN:
            await self._append(NoticeWidget(f"未知命令：{route.payload}", level="error"))
            return

        if not route.payload:
            if route.kind is CommandKind.CHAT:
                await self._append(NoticeWidget("用法：/chat <你的消息>", level="error"))
            return

        if route.kind is CommandKind.CHAT:
            await self._hide_welcome()
            await self._append(UserMessageWidget(route.payload, chat=True))
            await self.run_chat(route.payload)
            return

        await self._hide_welcome()
        await self._append(UserMessageWidget(route.payload))
        await self.run_agent(route.payload)

    async def run_agent(self, task: str) -> None:
        """Start the AgentLoop worker; lifecycle messages drive the UI."""
        if self._worker is not None and self._worker.is_alive:
            await self._append(NoticeWidget("当前任务仍在运行；追加指令将在 Session 阶段开放", level="system"))
            return

        config = load_config()
        config.workspace_root = self._workspace

        # Hard preflight gate: never spin up a worker with a broken setup.
        result = run_preflight(
            config,
            workspace=self._workspace,
            require_credentials=True,
        )
        if not result.ok:
            names = ", ".join(result.failing_names())
            await self._append(
                NoticeWidget(
                    f"preflight failed: {names}. Run `coding-agent check`.",
                    level="error",
                )
            )
            self._status().update("✗ preflight failed")
            return

        self._ui_state = initial_ui_state()
        self.query_one("#input", Input).disabled = True
        self._worker = AgentWorker(
            self,
            task=task,
            workspace=config.workspace_root,
            config=config,
        )
        self._worker.start()
        self._status().apply_state(self._ui_state)

    async def on_ui_agent_event(self, message: UiAgentEvent) -> None:
        """Reduce an event on the app thread, then update only its widgets."""
        event = message.event
        previous = self._ui_state
        next_state = reduce_event(previous, event)
        if next_state is previous:
            return
        self._ui_state = next_state
        await self._apply_event_to_widgets(event)
        self._status().apply_state(next_state)
        self._footer().apply_state(next_state)

    async def _apply_event_to_widgets(self, event: object) -> None:
        if isinstance(event, RunStarted):
            await self._hide_welcome()
        elif isinstance(event, ModelCompleted):
            response = event.response
            if response is not None and response.content.strip():
                assistant_key = (event.run_id, event.turn)
                assistant_widget = self._assistant_widgets.get(assistant_key)
                if assistant_widget is None:
                    assistant_widget = AssistantMessageWidget(response.content)
                    self._assistant_widgets[assistant_key] = assistant_widget
                    await self._append(assistant_widget)
                else:
                    assistant_widget.set_content(response.content)
        elif isinstance(event, AssistantReplied):
            assistant_key = (event.run_id, event.turn)
            assistant_widget = self._assistant_widgets.get(assistant_key)
            if assistant_widget is None:
                assistant_widget = AssistantMessageWidget(event.text)
                self._assistant_widgets[assistant_key] = assistant_widget
                await self._append(assistant_widget)
            else:
                assistant_widget.set_content(event.text)
        elif isinstance(event, (ToolStarted, ToolCompleted, ToolFailed)):
            tool_key = (event.run_id, event.action_id)
            tool_state = self._ui_state.tools.get(tool_key)
            if tool_state is None:
                return
            tool_widget = self._tool_widgets.get(tool_key)
            if tool_widget is None:
                tool_widget = ToolExecutionWidget(tool_state)
                self._tool_widgets[tool_key] = tool_widget
                await self._append(tool_widget)
            else:
                tool_widget.apply_state(tool_state)
        elif isinstance(event, ValidationCompleted):
            validation_key = (event.run_id, event.sequence)
            validation_widget = self._validation_widgets.get(validation_key)
            if validation_widget is None:
                validation_widget = ValidationWidget(
                    passed=event.passed,
                    summary=event.summary,
                    command=event.command,
                )
                self._validation_widgets[validation_key] = validation_widget
                await self._append(validation_widget)
        elif isinstance(event, FeedbackRecorded):
            notice_key = (event.run_id, event.sequence)
            if notice_key not in self._notice_widgets:
                notice_widget = NoticeWidget(event.content, level="feedback")
                self._notice_widgets[notice_key] = notice_widget
                await self._append(notice_widget)
        elif isinstance(event, ModelFailed):
            await self._append(NoticeWidget(event.error or event.error_type, level="error"))
        elif isinstance(event, FinishAccepted):
            await self._update_final(event.run_id)
        elif isinstance(event, RunFinished):
            await self._update_final(event.run_id)
            self._finish_agent_input()
        elif isinstance(event, RunFailed):
            for tool_key, tool_state in self._ui_state.tools.items():
                tool_widget = self._tool_widgets.get(tool_key)
                if tool_widget is not None:
                    tool_widget.apply_state(tool_state)
            await self._update_final(event.run_id)
            self._finish_agent_input()
        elif isinstance(event, (TurnStarted, TurnEnded)):
            return

    async def _update_final(self, run_id: str) -> None:
        widget = self._final_widgets.get(run_id)
        if widget is None:
            widget = FinalResultWidget()
            self._final_widgets[run_id] = widget
            await self._append(widget)
        widget.apply_state(self._ui_state)

    def on_agent_worker_result(self, message: AgentWorkerResult) -> None:
        """Use the result only as a fallback when no terminal event arrived."""
        if not self._ui_state.terminal:
            self._status().update(
                f"✓ finished · {message.result.steps} steps · {message.result.total_tokens:,} tokens"
            )
        self._finish_agent_input()

    async def on_agent_worker_error(self, message: AgentWorkerError) -> None:
        """Surface an uncaught worker error without duplicating RunFailed."""
        if not self._ui_state.terminal:
            await self._append(NoticeWidget(str(message.error), level="error"))
            self._status().update("✗ error")
        self._finish_agent_input()

    def _finish_agent_input(self) -> None:
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = False
        input_widget.focus()

    async def run_chat(self, user_msg: str) -> None:
        """Run the explicit no-tools chat mode while preserving history."""
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = True
        self._status().update("✻ chat…")
        try:
            from coding_agent.model.client import ModelClient

            client = ModelClient.from_config(load_config())
            self._chat_history.append({"role": "user", "content": user_msg})
            messages: list[dict[str, str]] = [
                {"role": "system", "content": self._chat_system},
                *self._chat_history,
            ]
            loop = asyncio.get_running_loop()
            reply = await loop.run_in_executor(
                None,
                lambda: client.chat(messages=messages, max_tokens=500),
            )
            self._chat_history.append({"role": "assistant", "content": reply.strip()})
            await self._append(AssistantMessageWidget(reply.strip()))
            self._status().update(f"chat · {len(self._chat_history) // 2} turns")
        except Exception as exc:
            await self._append(NoticeWidget(str(exc), level="error"))
            self._status().update("✗ error")
        finally:
            input_widget.disabled = False
            input_widget.focus()

    def action_clear_log(self) -> None:
        """Clear the component transcript, preserving the composer."""
        self.call_after_refresh(self._reset_transcript)

    def action_toggle_tools(self) -> None:
        """Expand all tool cards, or collapse them when already expanded."""
        if not self._tool_widgets:
            return
        expand = any(not widget.expanded for widget in self._tool_widgets.values())
        for widget in self._tool_widgets.values():
            widget.set_expanded(expand)

    async def on_key(self, event: Key) -> None:
        """Return focus to the composer on Escape without cancelling a run.

        Skips the focus call when the Input is currently disabled (a worker
        is running): focusing a disabled widget raises, and we do not want
        the act of pressing Escape to surface a redraw error.
        """
        if event.key != "escape":
            return
        try:
            input_widget = self.query_one("#input", Input)
        except Exception:
            return
        if input_widget.disabled:
            event.stop()
            return
        input_widget.focus()
        event.stop()
