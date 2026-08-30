"""Tests for the in-memory AgentSession contract."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from coding_agent.session import (
    AgentSession,
    PreviousRunSnapshot,
    SessionActiveError,
    SessionCapacityError,
    SessionMessage,
    SessionStateError,
)


def test_tool_calls_and_results_are_strictly_paired(tmp_path: Path) -> None:
    session = AgentSession(tmp_path)
    run = session.begin_run("tools")
    session.record_tool_call(
        tool_call_id="call-1", tool_name="read_file", arguments={"path": "a"}, run_id=run.run_id
    )
    with pytest.raises(SessionStateError):
        session.record_tool_result(
            tool_call_id="orphan", tool_name="read_file", content="x", success=True, run_id=run.run_id
        )
    with pytest.raises(SessionStateError):
        session.record_tool_call(
            tool_call_id="call-1", tool_name="read_file", arguments={}, run_id=run.run_id
        )
    with pytest.raises(SessionStateError):
        session.record_tool_result(
            tool_call_id="call-1", tool_name="wrong", content="x", success=True, run_id=run.run_id
        )
    session.record_tool_result(
        tool_call_id="call-1", tool_name="read_file", content="x", success=True, run_id=run.run_id
    )
    with pytest.raises(SessionStateError):
        session.record_tool_result(
            tool_call_id="call-1", tool_name="read_file", content="x", success=True, run_id=run.run_id
        )
    assert len(session.messages) == 2


def test_complete_rejects_unresolved_tool_call(tmp_path: Path) -> None:
    session = AgentSession(tmp_path)
    run = session.begin_run("tools")
    session.record_tool_call(
        tool_call_id="call-1", tool_name="read_file", arguments={}, run_id=run.run_id
    )
    with pytest.raises(SessionStateError, match="unresolved"):
        session.complete_run(run)
    assert session.active_run is None


    arguments = {"nested": {"items": ["before"]}}
    message = SessionMessage(role="assistant", arguments=arguments)

    arguments["nested"]["items"].append("after")

    assert message.arguments["nested"]["items"] == ("before",)
    with pytest.raises(TypeError):
        message.arguments["new"] = "value"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        message.content = "changed"  # type: ignore[misc]


def test_message_field_limit_is_explicit() -> None:
    with pytest.raises(SessionCapacityError, match="content"):
        SessionMessage(role="user", content="x" * 64_001)


def test_history_is_complete_and_not_silently_evicted(tmp_path: Path) -> None:
    session = AgentSession(tmp_path, max_messages=2)
    run = session.begin_run("task")
    session.record_user("one", run_id=run.run_id)
    session.record_assistant("two", run_id=run.run_id)

    with pytest.raises(SessionCapacityError, match="not be silently discarded"):
        session.record_user("three", run_id=run.run_id)
    assert [message.content for message in session.messages] == ["one", "two"]


def test_begin_run_owns_unique_run_ids_and_active_guard(tmp_path: Path) -> None:
    session = AgentSession(tmp_path)
    first = session.begin_run("first")
    with pytest.raises(SessionActiveError):
        session.begin_run("second")
    with pytest.raises(SessionActiveError):
        session.clear()

    session.complete_run(first, PreviousRunSnapshot(run_id=first.run_id, summary="done"))
    second = session.begin_run("second")
    assert first.run_id != second.run_id
    assert session.session_id == session.session_id


def test_records_require_current_active_run(tmp_path: Path) -> None:
    session = AgentSession(tmp_path)
    with pytest.raises(SessionStateError):
        session.record_user("without run")

    session.begin_run("task")
    with pytest.raises(SessionStateError):
        session.record_user("wrong", run_id="run_other")


def test_complete_and_fail_create_bounded_snapshots_and_release_guard(tmp_path: Path) -> None:
    session = AgentSession(tmp_path)
    completed = session.begin_run("complete")
    snapshot = session.complete_run(
        completed,
        summary="x" * 10_000,
        reason="assistant_reply",
    ) if False else session.complete_run(
        completed,
        PreviousRunSnapshot(
            run_id=completed.run_id,
            summary="x" * 10_000,
        ),
    )
    assert len(snapshot.summary) <= 4_000
    assert session.active_run is None
    assert session.runs[0].status == "completed"

    failed = session.begin_run("fail")
    failed_snapshot = session.fail_run(failed, RuntimeError("boom"))
    assert failed_snapshot.outcome == "failed"
    assert failed_snapshot.error == "boom"
    assert session.active_run is None
    assert session.snapshot == failed_snapshot


def test_finish_exception_releases_active_guard(tmp_path: Path) -> None:
    session = AgentSession(tmp_path)
    run = session.begin_run("task")
    with pytest.raises(TypeError):
        session.complete_run(run, snapshot="not a snapshot")  # type: ignore[arg-type]
    assert session.active_run is None
    next_run = session.begin_run("next")
    assert next_run.run_id != run.run_id


def test_clear_removes_history_runs_and_snapshot(tmp_path: Path) -> None:
    session = AgentSession(tmp_path)
    run = session.begin_run("task")
    session.record_user("message", run_id=run.run_id)
    session.complete_run(run)
    session.clear()

    assert session.messages == ()
    assert session.runs == ()
    assert session.snapshot is None


def test_different_workspaces_do_not_share_session(tmp_path: Path) -> None:
    left = AgentSession(tmp_path / "left")
    right = AgentSession(tmp_path / "right")
    assert left.session_id != right.session_id
    assert left.workspace != right.workspace


def test_snapshot_from_terminal_facts_is_bounded() -> None:
    class Facts:
        summary = "summary"
        validation = "validation"
        modified_files = ["a.py"]
        steps = 3
        total_tokens = 9
        status = "COMPLETED"

    snapshot = PreviousRunSnapshot.from_facts("run_1", Facts(), reason="finish")
    assert snapshot.summary == "summary"
    assert snapshot.validation == "validation"
    assert snapshot.modified_files == ("a.py",)
    assert snapshot.steps == 3
