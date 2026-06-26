from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.commands import models, run
from helmcode.core.config import HelmcodeConfig


def _config() -> HelmcodeConfig:
    return HelmcodeConfig(
        model_roles={
            "default": "main:default",
            "fast": "main:fast",
            "planning": "main:planner",
            "coding": "main:coder",
            "review": "main:review",
        }
    )


class FakeAllocation:
    def to_dict(self) -> dict[str, object]:
        return {
            "task": "add helper",
            "detected_task_type": "code_patch",
            "assignments": [{"agent_id": "coder", "model_id": "main:coder"}],
            "cost_breakdown": {"estimated_savings_score": 3},
        }


def test_run_recommend_uses_coding_plan_allocation(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    printed: list[object] = []

    def fake_build_allocation(**kwargs):
        calls.append(kwargs)
        return FakeAllocation()

    monkeypatch.setattr(run, "load_config", _config)
    monkeypatch.setattr(run.agents_command, "build_allocation", fake_build_allocation)
    monkeypatch.setattr(run.agents_command, "print_allocation", printed.append)

    run.run_task(
        task="refactor routing and implement a safer path",
        workspace=tmp_path,
        yes=False,
        routing="recommend",
        model="main:coder",
        max_cost_score=7,
        no_tests=False,
        no_preplan_cache=False,
    )

    assert calls == [
        {
            "task": "refactor routing and implement a safer path",
            "workspace": tmp_path,
            "routing": "recommend",
            "model": "main:coder",
            "model_preset": "balanced",
            "model_overrides": {},
            "include_repair": True,
            "max_cost_score": 7,
        }
    ]
    assert isinstance(printed[0], FakeAllocation)


def test_models_recommend_json_outputs_coding_plan_allocation(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_build_allocation(**kwargs):
        calls.append(kwargs)
        return FakeAllocation()

    monkeypatch.setattr(models.agents_command, "build_allocation", fake_build_allocation)

    result = CliRunner().invoke(
        models.app,
        [
            "recommend",
            "add helper",
            "--workspace",
            str(tmp_path),
            "--model",
            "main:coder",
            "--role-model",
            "coder=main:pro-coder",
            "--include-repair",
            "--max-cost-score",
            "5",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "task": "add helper",
        "detected_task_type": "code_patch",
        "assignments": [{"agent_id": "coder", "model_id": "main:coder"}],
        "cost_breakdown": {"estimated_savings_score": 3},
    }
    assert calls == [
        {
            "task": "add helper",
            "workspace": tmp_path,
            "routing": "quota",
            "model": "main:coder",
            "model_preset": "balanced",
            "model_overrides": {"coder": "main:pro-coder"},
            "include_repair": True,
            "max_cost_score": 5,
        }
    ]
