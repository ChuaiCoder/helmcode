from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.commands import sessions
from helmcode.memory.session_store import SessionStore


def test_sessions_list_json_uses_workspace_store(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})

    result = CliRunner().invoke(
        sessions.app,
        ["--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["session_id"] == "session-a"
    assert payload[0]["task"] == "add tests"


def test_sessions_events_json_can_filter_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})
    store.record("session-b", "user_message", {"content": "review patch"})

    result = CliRunner().invoke(
        sessions.app,
        ["events", "session-a", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["session_id"] == "session-a"
    assert payload[0]["payload"] == {"content": "add tests"}


def test_sessions_stats_json_reports_aggregate_counts(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "model_called", {"model_id": "main:planner"})
    store.record("session-a", "command_result", {"ok": True})

    result = CliRunner().invoke(
        sessions.app,
        ["stats", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["session_count"] == 1
    assert payload["event_count"] == 2
    assert payload["model_call_count"] == 1
    assert payload["command_result_count"] == 1
