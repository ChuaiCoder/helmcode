from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.memory.session_store import SessionStore


def test_tokens_command_aggregates_usage_and_allocations(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "model_called",
        {
            "role": "planning",
            "task_type": "plan",
            "model_id": "main:planner",
            "routing_mode": "quota",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 30,
                "total_tokens": 130,
                "cached_tokens": 60,
            },
        },
    )
    store.record(
        "session-a",
        "model_called",
        {
            "role": "coding",
            "task_type": "code_patch",
            "model_id": "main:coder",
            "routing_mode": "quota",
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
        "session-a",
        "task_allocated",
        {
            "task": "add tests",
            "detected_task_type": "code_patch",
            "selected_cost_score": 5,
            "assignments": [
                {
                    "agent_id": "planner",
                    "context_token_estimate": 50,
                    "quota_reservations": [
                        {"unit": "token", "reserved_amount": 2550},
                        {"unit": "request", "reserved_amount": 1},
                    ],
                },
                {
                    "agent_id": "coder",
                    "context_token_estimate": 50,
                    "quota_unit": "token",
                    "quota_reserved_amount": 4050,
                },
            ],
        },
    )

    result = CliRunner().invoke(app, ["tokens", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["model_call_count"] == 2
    assert payload["summary"]["prompt_tokens"] == 300
    assert payload["summary"]["completion_tokens"] == 110
    assert payload["summary"]["total_tokens"] == 410
    assert payload["summary"]["cached_tokens"] == 80
    assert payload["summary"]["cache_miss_tokens"] == 220
    assert payload["summary"]["cache_hit_rate"] == 80 / 300
    assert payload["summary"]["allocation_context_token_estimate"] == 100
    assert payload["summary"]["allocation_quota_token_reserved"] == 6600
    by_model = {item["name"]: item for item in payload["by_model"]}
    assert by_model["main:coder"]["total_tokens"] == 280
    assert by_model["main:planner"]["cache_hit_rate"] == 0.6


def test_tokens_command_filters_by_session_and_limit(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "model_called",
        {"model_id": "old", "usage": {"total_tokens": 10}},
    )
    store.record(
        "session-b",
        "model_called",
        {"model_id": "new", "usage": {"total_tokens": 20}},
    )

    result = CliRunner().invoke(
        app,
        ["tokens", "--workspace", str(tmp_path), "--session", "session-b", "--limit", "1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["session_id"] == "session-b"
    assert payload["summary"]["model_call_count"] == 1
    assert payload["summary"]["total_tokens"] == 20
    assert payload["recent_model_calls"][0]["model_id"] == "new"


def test_tokens_command_prints_tables(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "model_called",
        {
            "role": "planning",
            "task_type": "plan",
            "model_id": "main:planner",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )

    result = CliRunner().invoke(app, ["tokens", "--workspace", str(tmp_path)])

    assert result.exit_code == 0
    assert "Token usage" in result.output
    assert "Tokens by model" in result.output
    assert "main:planner" in result.output
