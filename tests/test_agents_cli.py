from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.agent.allocation import AgentAssignment
from helmcode.cli.commands import agents


def test_agents_plan_json_outputs_machine_readable_contract(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class FakeAllocation:
        def to_dict(self) -> dict[str, object]:
            return {
                "task": "add helper",
                "blocked": False,
                "assignments": [{"agent_id": "coder", "model_id": "main:coder"}],
            }

    def fake_build_allocation(**kwargs):
        calls.append(kwargs)
        return FakeAllocation()

    monkeypatch.setattr(agents, "build_allocation", fake_build_allocation)
    result = CliRunner().invoke(
        agents.app,
        [
            "plan",
            "add helper",
            "--workspace",
            str(tmp_path),
            "--routing",
            "quota",
            "--model",
            "main:coder",
            "--max-cost-score",
            "3",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "task": "add helper",
        "blocked": False,
        "assignments": [{"agent_id": "coder", "model_id": "main:coder"}],
    }
    assert calls == [
        {
            "task": "add helper",
            "workspace": tmp_path,
            "routing": "quota",
            "model": "main:coder",
            "include_repair": False,
            "max_cost_score": 3,
        }
    ]


def test_quota_text_shows_projected_remaining_after_allocation() -> None:
    assignment = AgentAssignment(
        agent_id="scout",
        role="fast",
        task_type="repo_scan",
        purpose="scan cheaply",
        model_id="main:fast",
        reason="selected for repo_scan",
        required=False,
        estimated_cost_score=1,
        quota_policy_id="fast_daily",
        quota_remaining=2,
        quota_remaining_after=1,
    )

    assert agents._quota_text(assignment) == "fast_daily: 2 left, 1 after allocation"


def test_quota_text_shows_token_reservation_amount() -> None:
    assignment = AgentAssignment(
        agent_id="planner",
        role="planning",
        task_type="plan",
        purpose="plan",
        model_id="main:planner",
        reason="selected for plan",
        required=True,
        estimated_cost_score=2,
        quota_policy_id="planning_tokens",
        quota_unit="token",
        quota_reserved_amount=2_500,
        quota_remaining=3_000,
        quota_remaining_after=500,
    )

    assert agents._quota_text(assignment) == (
        "planning_tokens: 3000 left, reserves 2500 token, 500 after allocation"
    )


def test_quota_text_shows_multiple_reservations() -> None:
    assignment = AgentAssignment(
        agent_id="planner",
        role="planning",
        task_type="plan",
        purpose="plan",
        model_id="main:planner",
        reason="selected for plan",
        required=True,
        estimated_cost_score=2,
        quota_reservations=[
            {
                "policy_id": "planning_requests",
                "unit": "request",
                "reserved_amount": 1,
                "remaining": 2,
                "remaining_after": 1,
                "resets_at": None,
            },
            {
                "policy_id": "planning_tokens",
                "unit": "token",
                "reserved_amount": 2_500,
                "remaining": 3_000,
                "remaining_after": 500,
                "resets_at": None,
            },
        ],
    )

    assert agents._quota_text(assignment) == (
        "planning_requests/request: 2 left, 1 after allocation; "
        "planning_tokens/token: 3000 left, reserves 2500 token, 500 after allocation"
    )
