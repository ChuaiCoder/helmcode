from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.memory.session_store import SessionStore


def test_allocations_command_lists_history_json(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "task_allocated",
        {
            "task": "add tests",
            "detected_task_type": "code_patch",
            "complexity": "low",
            "strategy": "quota-saving direct path",
            "estimated_calls": 2,
            "baseline_calls": 2,
            "baseline_model_id": "main:coder",
            "baseline_cost_score": 8,
            "selected_cost_score": 5,
            "estimated_savings_score": 3,
            "max_cost_score": 6,
            "budget_exceeded": False,
            "blocked": False,
            "warnings": [],
            "assignments": [
                {
                    "agent_id": "planner",
                    "role": "planning",
                    "task_type": "plan",
                    "model_id": "main:planner",
                    "required": True,
                    "estimated_cost_score": 2,
                    "model_cost_tier": "medium",
                    "context_token_estimate": 100,
                    "quota_reservations": [{"unit": "request", "reserved_amount": 1}],
                },
                {
                    "agent_id": "coder",
                    "role": "coding",
                    "task_type": "code_patch",
                    "model_id": "main:coder",
                    "required": True,
                    "estimated_cost_score": 3,
                    "model_cost_tier": "high",
                    "context_token_estimate": 100,
                },
            ],
        },
    )
    store.record(
        "session-b",
        "task_allocated",
        {
            "task": "blocked refactor",
            "detected_task_type": "code_patch",
            "complexity": "high",
            "estimated_calls": 1,
            "baseline_calls": 3,
            "baseline_cost_score": 12,
            "selected_cost_score": 9,
            "estimated_savings_score": 3,
            "budget_exceeded": True,
            "blocked": True,
            "warnings": ["blocked:coder:no quota"],
            "assignments": [],
        },
    )

    result = CliRunner().invoke(app, ["allocations", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["allocation_count"] == 2
    assert payload["baseline_cost_score"] == 20
    assert payload["selected_cost_score"] == 14
    assert payload["estimated_savings_score"] == 6
    assert payload["budget_exceeded_count"] == 1
    assert payload["blocked_count"] == 1
    assert payload["allocations"][0]["session_id"] == "session-b"
    assert payload["allocations"][1]["agents"] == ["planner", "coder"]
    assert payload["allocations"][1]["models"] == ["main:planner", "main:coder"]
    assert payload["allocations"][1]["assignments"][0]["quota_reservations"] == [
        {"unit": "request", "reserved_amount": 1}
    ]


def test_allocations_command_filters_by_session_and_plans_alias(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "task_allocated",
        {
            "task": "old",
            "baseline_cost_score": 5,
            "selected_cost_score": 3,
            "estimated_savings_score": 2,
            "assignments": [],
        },
    )
    store.record(
        "session-b",
        "task_allocated",
        {
            "task": "new",
            "baseline_cost_score": 8,
            "selected_cost_score": 4,
            "estimated_savings_score": 4,
            "assignments": [],
        },
    )

    result = CliRunner().invoke(
        app,
        ["plans", "--workspace", str(tmp_path), "--session", "session-a", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["session_id"] == "session-a"
    assert payload["allocation_count"] == 1
    assert payload["allocations"][0]["task"] == "old"


def test_allocations_command_prints_table(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "task_allocated",
        {
            "task": "plan repo",
            "detected_task_type": "plan",
            "baseline_cost_score": 4,
            "selected_cost_score": 2,
            "estimated_savings_score": 2,
            "assignments": [
                {
                    "agent_id": "planner",
                    "model_id": "main:planner",
                    "estimated_cost_score": 2,
                }
            ],
        },
    )

    result = CliRunner().invoke(app, ["allocations", "--workspace", str(tmp_path)])

    assert result.exit_code == 0
    assert "Coding Plan allocation history" in result.output
    assert "Allocations" in result.output
    assert "planner" in result.output
