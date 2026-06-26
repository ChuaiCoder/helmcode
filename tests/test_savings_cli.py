from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.memory.session_store import SessionStore


def test_savings_command_aggregates_allocation_history(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "task_allocated",
        {
            "task": "refactor routing",
            "detected_task_type": "code_patch",
            "complexity": "medium",
            "estimated_calls": 3,
            "baseline_calls": 3,
            "baseline_cost_score": 12,
            "selected_cost_score": 6,
            "estimated_savings_score": 6,
            "budget_exceeded": False,
            "blocked": False,
            "assignments": [
                {
                    "agent_id": "scout",
                    "role": "fast",
                    "task_type": "repo_scan",
                    "model_id": "main:fast",
                    "required": False,
                    "estimated_cost_score": 1,
                    "context_token_estimate": 100,
                    "quota_reservations": [
                        {"unit": "request", "reserved_amount": 1},
                        {"unit": "token", "reserved_amount": 1600},
                    ],
                },
                {
                    "agent_id": "planner",
                    "role": "planning",
                    "task_type": "plan",
                    "model_id": "main:planner",
                    "required": True,
                    "estimated_cost_score": 2,
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
                    "context_token_estimate": 100,
                    "quota_reservations": [{"unit": "request", "reserved_amount": 1}],
                },
            ],
        },
    )
    store.record(
        "session-b",
        "task_allocated",
        {
            "task": "add tests",
            "detected_task_type": "code_patch",
            "complexity": "low",
            "estimated_calls": 2,
            "baseline_calls": 2,
            "baseline_cost_score": 8,
            "selected_cost_score": 5,
            "estimated_savings_score": 3,
            "budget_exceeded": True,
            "blocked": True,
            "assignments": [
                {
                    "agent_id": "planner",
                    "role": "planning",
                    "task_type": "plan",
                    "model_id": "main:planner",
                    "required": True,
                    "estimated_cost_score": 2,
                    "context_token_estimate": 0,
                },
                {
                    "agent_id": "coder",
                    "role": "coding",
                    "task_type": "code_patch",
                    "model_id": "main:coder",
                    "required": True,
                    "estimated_cost_score": 3,
                    "context_token_estimate": 0,
                },
            ],
        },
    )

    result = CliRunner().invoke(app, ["savings", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["allocation_count"] == 2
    assert payload["baseline_cost_score"] == 20
    assert payload["selected_cost_score"] == 11
    assert payload["estimated_savings_score"] == 9
    assert payload["savings_rate"] == 0.45
    assert payload["budget_exceeded_count"] == 1
    assert payload["blocked_count"] == 1
    assert payload["assignment_count"] == 5
    assert payload["required_assignment_count"] == 4
    assert payload["optional_assignment_count"] == 1
    assert payload["context_token_estimate"] == 300
    by_agent = {item["name"]: item for item in payload["by_agent"]}
    assert by_agent["coder"]["cost_score"] == 6
    assert by_agent["planner"]["assignment_count"] == 2
    by_model = {item["name"]: item for item in payload["by_model"]}
    assert by_model["main:fast"]["quota_reserved"] == {"request": 1, "token": 1600}


def test_savings_command_limit_uses_newest_allocations(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "task_allocated",
        {
            "task": "old",
            "baseline_cost_score": 10,
            "selected_cost_score": 9,
            "estimated_savings_score": 1,
            "assignments": [],
        },
    )
    store.record(
        "session-b",
        "task_allocated",
        {
            "task": "new",
            "baseline_cost_score": 10,
            "selected_cost_score": 3,
            "estimated_savings_score": 7,
            "assignments": [],
        },
    )

    result = CliRunner().invoke(
        app,
        ["savings", "--workspace", str(tmp_path), "--limit", "1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["allocation_count"] == 1
    assert payload["estimated_savings_score"] == 7
    assert payload["recent_allocations"][0]["task"] == "new"


def test_savings_command_prints_report(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record(
        "session-a",
        "task_allocated",
        {
            "task": "plan",
            "baseline_cost_score": 4,
            "selected_cost_score": 2,
            "estimated_savings_score": 2,
            "assignments": [
                {
                    "agent_id": "planner",
                    "role": "planning",
                    "task_type": "plan",
                    "model_id": "main:planner",
                    "required": True,
                    "estimated_cost_score": 2,
                }
            ],
        },
    )

    result = CliRunner().invoke(app, ["savings", "--workspace", str(tmp_path)])

    assert result.exit_code == 0
    assert "Coding Plan savings" in result.output
    assert "Cost by agent" in result.output
    assert "Cost by model" in result.output
