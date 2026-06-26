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
