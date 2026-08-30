"""Textual TUI application backed by componentized lifecycle views."""

from __future__ import annotations

from pathlib import Path
from time import monotonic

from textual.app import App, ComposeResult
from textual.events import Key
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input

from coding_agent import __version__
from coding_agent.config import load_config, run_preflight
from coding_agent.events import (
    AssistantReplied,
    FeedbackRecorded,
    FinishAccepted,
    ModelCompleted,
    ModelDelta,
    ModelFailed,
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    ToolCancelled,
    ToolCompleted,
    ToolFailed,
    ToolOutputDelta,
    ToolStarted,
    TurnEnded,
    TurnStarted,
    ValidationCompleted,
)
from coding_agent.session import AgentSession
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

    STREAM_RENDER_INTERVAL = 0.07

    CSS_PATH = "tui.css"
    BINDINGS = [
        ("ctrl+c", "quit_or_cancel", "Cancel / quit"),
        ("ctrl+l", "clear_log", "Clear"),
        ("ctrl+o", "toggle_tools", "Expand/collapse tools"),
    ]

    TITLE = "TraceForce Agent"
    SUB_TITLE = f"v{__version__}"
    CANCEL_EXIT_GUARD_SECONDS = 0.4

    def __init__(
        self,
        workspace: Path | None = None,
        *,
        env_file: Path | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__()
        self._workspace: Path = (workspace or Path.cwd()).resolve()
        self._env_file = env_file
        self._provider = provider
        self._session: AgentSession = AgentSession(workspace=self._workspace)
        self._ui_state: RunUiState = initial_ui_state()
        self._worker: AgentWorker | None = None
        self._worker_generation = 0
        self._cancel_requested_at: float | None = None
        self._welcome: WelcomeWidget | None = None
        self._assistant_widgets: dict[tuple[str, int], AssistantMessageWidget] = {}
        self._pending_assistant_renders: dict[tuple[str, int], str] = {}
        self._pending_tool_renders: set[tuple[str, str]] = set()
        self._stream_render_timer: Timer | None = None
        self._tool_widgets: dict[tuple[str, str], ToolExecutionWidget] = {}
        self._validation_widgets: dict[tuple[str, int], ValidationWidget] = {}
        self._notice_widgets: dict[tuple[str, int], NoticeWidget] = {}
        self._final_widgets: dict[str, FinalResultWidget] = {}

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
            config = load_config(
                env_file=self._env_file,
                provider=self._provider,
            )
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
                    f"preflight failed: {names} — see `tracef check`",
                    level="system",
                )
            )

    def _transcript(self) -> TranscriptView:
        return self.query_one("#transcript", TranscriptView)

    def _status(self) -> RunStatusWidget:
        return self.query_one("#run_status", RunStatusWidget)

    def _footer(self) -> FooterMetaWidget:
        return self.query_one("#footer_meta", FooterMetaWidget)

    def _cancel_stream_render_timer(self) -> None:
        if self._stream_render_timer is not None:
            self._stream_render_timer.stop()
            self._stream_render_timer = None

    def _flush_pending_stream_renders(
        self, stream_key: tuple[str, int] | tuple[str, str] | None = None
    ) -> None:
        if stream_key is None:
            assistant_keys = list(self._pending_assistant_renders)
        elif isinstance(stream_key[1], int):
            assistant_keys = [stream_key]
        else:
            assistant_keys = []
        for key in assistant_keys:
            content = self._pending_assistant_renders.pop(key, None)
            widget = self._assistant_widgets.get(key)
            if content is not None and widget is not None:
                widget.set_content(content)
        tool_keys = (
            list(self._pending_tool_renders)
            if stream_key is None
            else [stream_key] if isinstance(stream_key[1], str) else []
        )
        for tool_key in tool_keys:
            self._pending_tool_renders.discard(tool_key)
            tool_widget = self._tool_widgets.get(tool_key)
            tool_state = self._ui_state.tools.get(tool_key)
            if tool_widget is not None and tool_state is not None:
                tool_widget.apply_state(tool_state)
        if not self._pending_assistant_renders and not self._pending_tool_renders:
            self._cancel_stream_render_timer()

    def _flush_pending_assistant_renders(
        self, assistant_key: tuple[str, int] | None = None
    ) -> None:
        """Compatibility wrapper for callers and existing test hooks."""
        self._flush_pending_stream_renders(assistant_key)

    def _schedule_stream_render(self) -> None:
        if self._stream_render_timer is None:
            self._stream_render_timer = self.set_timer(
                self.STREAM_RENDER_INTERVAL,
                self._flush_pending_assistant_renders,
            )

    async def _append(self, widget: Widget) -> None:
        """Mount one transcript widget through the single transcript owner."""
        await self._transcript().append_entry(widget)

    async def _hide_welcome(self) -> None:
        if self._welcome is not None and self._welcome.is_attached:
            await self._welcome.remove()
        self._welcome = None

    async def _reset_transcript(self) -> None:
        self._flush_pending_assistant_renders()
        await self._transcript().clear_entries()
        self._assistant_widgets.clear()
        self._pending_assistant_renders.clear()
        self._pending_tool_renders.clear()
        self._tool_widgets.clear()
        self._validation_widgets.clear()
        self._notice_widgets.clear()
        self._final_widgets.clear()
        self._welcome = WelcomeWidget(self._workspace, id="welcome")
        await self._append(self._welcome)

    def _is_run_active(self) -> bool:
        """Whether any worker thread or session run is currently in-flight."""
        if self._worker is not None and self._worker.is_alive:
            return True
        return self._session.is_active

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Route a submitted line to a command, chat request, or Agent run.

        Active-run guard runs before :func:`route_input` so that ``/clear``,
        ``/workspace``, ``/chat`` and ordinary Agent tasks are all rejected
        while a worker is still in-flight. ``Ctrl+L`` and ``Esc`` bypass the
        guard because they do not start a run.
        """
        raw = event.value.strip()
        event.input.value = ""
        route = route_input(raw)

        if self._is_run_active() and route.kind in {
            CommandKind.CLEAR,
            CommandKind.WORKSPACE,
            CommandKind.CHAT,
            CommandKind.AGENT,
        }:
            await self._append(
                NoticeWidget(
                    "当前任务仍在运行；追加指令将在 Session 阶段开放",
                    level="system",
                )
            )
            return

        if route.kind is CommandKind.CLEAR:
            self._session.clear()
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
            self._session = AgentSession(workspace=self._workspace)
            await self._reset_transcript()
            self._ui_state = initial_ui_state()
            self._status().apply_state(self._ui_state)
            self._footer().set_workspace(new_path)
            self.query_one(BrandBarWidget).set_workspace(new_path)
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

        await self._hide_welcome()
        await self._append(UserMessageWidget(route.payload))
        await self.run_agent(route.payload)

    async def run_agent(self, task: str) -> None:
        """Start the AgentLoop worker; lifecycle messages drive the UI."""
        if self._is_run_active():
            await self._append(NoticeWidget("当前任务仍在运行；追加指令将在 Session 阶段开放", level="system"))
            return

        config = load_config(
            env_file=self._env_file,
            provider=self._provider,
        )
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
                    f"preflight failed: {names}. Run `tracef check`.",
                    level="error",
                )
            )
            self._status().update("✗ preflight failed")
            # Preflight failure must NOT touch the Session or fake a Run.
            return

        self._ui_state = initial_ui_state()
        self._cancel_requested_at = None
        self._worker_generation += 1
        self.query_one("#input", Input).disabled = True
        self._worker = AgentWorker(
            self,
            task=task,
            workspace=config.workspace_root,
            config=config,
            session=self._session,
            worker_id=self._worker_generation,
        )
        self._worker.start()
        self._status().apply_state(self._ui_state)

    async def on_ui_agent_event(self, message: UiAgentEvent) -> None:
        """Reduce an event on the app thread, then update only its widgets."""
        if (
            message.worker_id is not None
            and message.worker_id != self._active_worker_id()
        ):
            return
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
            self._flush_pending_assistant_renders()
            await self._hide_welcome()
        elif isinstance(event, ModelDelta):
            assistant_key = (event.run_id, event.turn)
            assistant_widget = self._assistant_widgets.get(assistant_key)
            draft = self._ui_state.assistant_drafts.get(assistant_key, "")
            if assistant_widget is None:
                if not draft:
                    return
                assistant_widget = AssistantMessageWidget(draft)
                self._assistant_widgets[assistant_key] = assistant_widget
                await self._append(assistant_widget)
            elif draft:
                self._pending_assistant_renders[assistant_key] = draft
                self._schedule_stream_render()
        elif isinstance(event, ModelCompleted):
            assistant_key = (event.run_id, event.turn)
            self._flush_pending_assistant_renders(assistant_key)
            response = event.response
            if response is not None:
                assistant_widget = self._assistant_widgets.get(assistant_key)
                if assistant_widget is None:
                    if response.content.strip():
                        assistant_widget = AssistantMessageWidget(response.content)
                        self._assistant_widgets[assistant_key] = assistant_widget
                        await self._append(assistant_widget)
                elif assistant_widget.content != response.content:
                    assistant_widget.set_content(response.content)
        elif isinstance(event, AssistantReplied):
            assistant_key = (event.run_id, event.turn)
            self._flush_pending_assistant_renders(assistant_key)
            assistant_widget = self._assistant_widgets.get(assistant_key)
            if assistant_widget is None:
                assistant_widget = AssistantMessageWidget(event.text)
                self._assistant_widgets[assistant_key] = assistant_widget
                await self._append(assistant_widget)
            else:
                if assistant_widget.content != event.text:
                    assistant_widget.set_content(event.text)
        elif isinstance(event, ToolOutputDelta):
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
                self._pending_tool_renders.add(tool_key)
                self._schedule_stream_render()
        elif isinstance(event, ToolStarted):
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
        elif isinstance(event, (ToolCompleted, ToolFailed, ToolCancelled)):
            tool_key = (event.run_id, event.action_id)
            self._flush_pending_stream_renders(tool_key)
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
            self._flush_pending_assistant_renders((event.run_id, event.turn))
            await self._append(NoticeWidget(event.error or event.error_type, level="error"))
        elif isinstance(event, FinishAccepted):
            self._flush_pending_assistant_renders()
            await self._update_final(event.run_id)
        elif isinstance(event, (RunFinished, RunFailed, RunCancelled)):
            self._flush_pending_assistant_renders()
            if isinstance(event, RunFinished):
                await self._update_final(event.run_id)
            elif isinstance(event, RunFailed):
                for tool_key, tool_state in self._ui_state.tools.items():
                    tool_widget = self._tool_widgets.get(tool_key)
                    if tool_widget is not None:
                        tool_widget.apply_state(tool_state)
                await self._update_final(event.run_id)
            else:
                for tool_key, tool_state in self._ui_state.tools.items():
                    tool_widget = self._tool_widgets.get(tool_key)
                    if tool_widget is not None:
                        tool_widget.apply_state(tool_state)
                await self._update_final(event.run_id)

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
        """Final teardown after a worker thread has fully returned.

        This is the only place that re-enables the composer Input. Doing it
        here (not in the ``RunFinished`` lifecycle event) guarantees that
        ``session.complete_run()`` has already returned on the worker thread
        before a new run can be submitted.
        """
        if message.worker_id is not None and message.worker_id != self._active_worker_id():
            return
        if not self._ui_state.terminal:
            self._status().update(
                f"✓ finished · {message.result.steps} steps · {message.result.total_tokens:,} tokens"
            )
        self._complete_worker(message.worker_id)

    async def on_agent_worker_error(self, message: AgentWorkerError) -> None:
        """Surface an uncaught worker error without duplicating RunFailed.

        Mirrors :meth:`on_agent_worker_result`: this is the only place that
        re-enables the composer Input on error, so it always runs after the
        worker thread has returned and ``session.fail_run()`` released the
        active-run guard.
        """
        if message.worker_id is not None and message.worker_id != self._active_worker_id():
            return
        if not self._ui_state.terminal:
            await self._append(NoticeWidget(str(message.error), level="error"))
            self._status().update("✗ error")
        self._complete_worker(message.worker_id)

    def _active_worker_id(self) -> int | None:
        return self._worker.worker_id if self._worker is not None else None

    def _complete_worker(self, worker_id: int | None = None) -> None:
        """Single teardown path for the worker.

        Drops the worker reference so subsequent submissions see a clean
        state, then re-enables the composer Input and refocuses it.
        """
        if worker_id is not None and worker_id != self._active_worker_id():
            return
        self._flush_pending_assistant_renders()
        self._worker = None
        self._cancel_requested_at = None
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = False
        input_widget.focus()

    def _cancel_exit_guard_active(self) -> bool:
        """Whether a recent cancellation request should absorb key repeats."""
        requested_at = self._cancel_requested_at
        return (
            requested_at is not None
            and monotonic() - requested_at < self.CANCEL_EXIT_GUARD_SECONDS
        )

    def action_quit_or_cancel(self) -> None:
        """Cancel once, then exit only after an explicit later keypress."""
        if self._worker is None or not self._worker.is_alive:
            if self._cancel_exit_guard_active():
                return
            self.exit()
            return
        if self._worker.cancellation_token.is_cancelled:
            if self._cancel_exit_guard_active():
                return
            self.exit()
            return
        if self._worker.cancel():
            self._cancel_requested_at = monotonic()
            self._status().update("• cancelling…")

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
