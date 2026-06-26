from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app as main_app
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
    store.record(
        "session-a",
        "task_allocated",
        {
            "baseline_cost_score": 8,
            "selected_cost_score": 3,
            "estimated_savings_score": 5,
        },
    )
    store.record(
        "session-a",
        "model_called",
        {
            "model_id": "main:planner",
            "usage": {
                "prompt_tokens": 25,
                "completion_tokens": 5,
                "total_tokens": 30,
                "cached_tokens": 10,
            },
        },
    )
    store.record("session-a", "command_result", {"ok": True})

    result = CliRunner().invoke(
        sessions.app,
        ["stats", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["session_count"] == 1
    assert payload["event_count"] == 3
    assert payload["model_call_count"] == 1
    assert payload["model_prompt_tokens"] == 25
    assert payload["model_completion_tokens"] == 5
    assert payload["model_total_tokens"] == 30
    assert payload["model_cached_tokens"] == 10
    assert payload["coding_plan_allocation_count"] == 1
    assert payload["coding_plan_baseline_cost_score"] == 8
    assert payload["coding_plan_selected_cost_score"] == 3
    assert payload["coding_plan_estimated_savings_score"] == 5
    assert payload["command_result_count"] == 1


def test_sessions_replay_json_outputs_ordered_events(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})
    store.record("session-a", "model_called", {"model_id": "main:planner"})

    result = CliRunner().invoke(
        sessions.app,
        ["replay", "session-a", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [event["event_type"] for event in payload] == ["user_message", "model_called"]


def test_sessions_diff_json_compares_two_sessions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})
    store.record(
        "session-a",
        "model_called",
        {
            "model_id": "main:planner",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cached_tokens": 50,
            },
        },
    )
    store.record(
        "session-a",
        "task_allocated",
        {
            "baseline_cost_score": 8,
            "selected_cost_score": 4,
            "estimated_savings_score": 4,
            "assignments": [
                {
                    "context_token_estimate": 100,
                    "quota_reservations": [{"unit": "token", "reserved_amount": 2000}],
                }
            ],
        },
    )
    store.record("session-b", "user_message", {"content": "add tests and patch"})
    store.record(
        "session-b",
        "model_called",
        {
            "model_id": "main:planner",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cached_tokens": 50,
            },
        },
    )
    store.record(
        "session-b",
        "model_called",
        {
            "model_id": "main:coder",
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 80,
                "total_tokens": 280,
                "cached_tokens": 20,
                "cache_miss_tokens": 180,
            },
        },
    )
    store.record(
        "session-b",
        "task_allocated",
        {
            "baseline_cost_score": 12,
            "selected_cost_score": 7,
            "estimated_savings_score": 5,
            "budget_exceeded": True,
            "blocked": True,
            "assignments": [
                {
                    "context_token_estimate": 100,
                    "quota_reservations": [{"unit": "token", "reserved_amount": 2500}],
                },
                {
                    "context_token_estimate": 100,
                    "quota_unit": "token",
                    "quota_reserved_amount": 4200,
                },
            ],
        },
    )
    store.record("session-b", "patch_created", {"files": ["app.py"]})

    result = CliRunner().invoke(
        sessions.app,
        ["diff", "session-a", "session-b", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["event_count_delta"] == 2
    assert payload["event_type_delta"]["patch_created"] == 1
    assert payload["model_calls_added"] == ["main:coder"]
    assert payload["patch_files_added"] == ["app.py"]
    assert payload["token_delta"]["model_total_tokens"] == 280
    assert payload["token_delta"]["model_cached_tokens"] == 20
    assert payload["token_delta"]["model_cache_miss_tokens"] == 180
    assert payload["coding_plan_cost_delta"]["coding_plan_selected_cost_score"] == 3
    assert payload["coding_plan_cost_delta"]["coding_plan_estimated_savings_score"] == 1
    assert payload["coding_plan_cost_delta"]["coding_plan_context_token_estimate"] == 100
    assert payload["coding_plan_cost_delta"]["coding_plan_quota_token_reserved"] == 4700
    assert payload["coding_plan_cost_delta"]["coding_plan_budget_exceeded_count"] == 1


def test_sessions_prune_json_deletes_old_sessions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "first"})
    store.record("session-b", "user_message", {"content": "second"})

    result = CliRunner().invoke(
        sessions.app,
        ["prune", "--workspace", str(tmp_path), "--keep", "1", "--yes", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [session["session_id"] for session in payload] == ["session-a"]
    assert [session.session_id for session in store.list_sessions(limit=10)] == ["session-b"]


def test_top_level_replay_alias_works(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})

    result = CliRunner().invoke(
        main_app,
        ["replay", "session-a", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)[0]["session_id"] == "session-a"


def test_replay_unknown_session_fails(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        sessions.app,
        ["replay", "missing-session", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 1
    assert "No events found" in result.output
