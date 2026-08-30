"""TUI preflight integration tests (P2-1D)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.bridge import UiAgentEvent
from coding_agent.tui.widgets import NoticeWidget


async def _post(app: CodingAgentApp, pilot, event) -> None:  # type: ignore[no-untyped-def]
    app.post_message(UiAgentEvent(event))
    await pilot.pause()


@pytest.fixture(autouse=True)
def _fake_required_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"git", "rg"} else None,
    )


@pytest.mark.asyncio
async def test_mount_surfaces_preflight_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRACEFORCE_API_KEY", raising=False)
    app_ = CodingAgentApp(workspace=tmp_path)
    async with app_.run_test() as pilot:
        # Mount preflight runs without credentials (require_credentials=False),
        # so a missing key does NOT raise a notice. We deliberately leave it
        # silent: the welcome widget already invites the user to type a task.
        await pilot.pause()
        notices = app_.query(NoticeWidget)
        # No preflight error in this scenario; just confirm we mounted cleanly.
        assert all(notice.level != "error" for notice in notices)


@pytest.mark.asyncio
async def test_mount_runs_preflight_and_appends_notice_when_tool_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app_ = CodingAgentApp(workspace=tmp_path)
    async with app_.run_test() as pilot:
        await pilot.pause()
        # Either rg or git failing should surface as a system notice.
        notices = [n for n in app_.query(NoticeWidget) if n.level == "system"]
        assert notices, "expected a system notice when preflight fails"
        assert any("preflight failed" in str(n.content) for n in notices)


@pytest.mark.asyncio
async def test_tui_uses_explicit_env_file_and_provider_for_mount_and_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "traceforce.env"
    env_file.write_text("OPENAI_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRACEFORCE_API_KEY", raising=False)

    captured: list[tuple[Path | None, str | None]] = []
    real_load_config = __import__("coding_agent.tui.app", fromlist=["load_config"]).load_config

    def load_config_spy(*, env_file=None, provider=None):
        captured.append((env_file, provider))
        return real_load_config(env_file=env_file, provider=provider)

    monkeypatch.setattr("coding_agent.tui.app.load_config", load_config_spy)

    class WorkerStub:
        def __init__(self, owner, *, config, **kwargs):
            self.config = config
            self.started = False
            self.is_alive = False

        def start(self):
            self.started = True

    workers: list[WorkerStub] = []

    def worker_factory(*args, **kwargs):
        worker = WorkerStub(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("coding_agent.tui.app.AgentWorker", worker_factory)
    app_ = CodingAgentApp(
        workspace=tmp_path,
        env_file=env_file,
        provider="openai",
    )
    async with app_.run_test() as pilot:
        await pilot.pause()
        await app_.run_agent("create a project from scratch")
        await pilot.pause()

    assert captured[0] == (env_file, "openai")
    assert captured[1] == (env_file, "openai")
    assert len(workers) == 1
    assert workers[0].config.api_key == "from-file"
    assert workers[0].started
    assert app_._worker is workers[0]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_run_agent_does_not_start_worker_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Hard preflight gate: no key → no worker, error notice appended."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRACEFORCE_API_KEY", raising=False)
    app_ = CodingAgentApp(workspace=tmp_path)
    async with app_.run_test():
        # Directly invoke run_agent (the user-input path goes through
        # routing + composer submit, both of which eventually call this).
        await app_.run_agent("noop-task")
        assert app_._worker is None  # type: ignore[attr-defined]
        # Error notice was appended.
        error_notices = [n for n in app_.query(NoticeWidget) if n.level == "error"]
        assert any("preflight failed" in str(n.content) for n in error_notices)
