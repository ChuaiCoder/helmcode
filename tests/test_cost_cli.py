from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app


def test_cost_command_outputs_context_and_allocation_json(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("project overview\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["cost", "plan @README.md", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["context"]["explicit_references"] == ["README.md"]
    assert payload["context"]["explicit_context_tokens"] > 0
    assert payload["summary"]["detected_task_type"] == "plan"
    assert payload["summary"]["estimated_calls"] >= 1
    assert payload["allocation"]["task"] == "plan @README.md"


def test_cost_command_exposes_auto_effective_preset(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "cost",
            "refactor the whole project architecture and implement a large routing change",
            "--workspace",
            str(tmp_path),
            "--preset",
            "auto",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["model_preset"] == "auto"
    assert payload["summary"]["effective_model_preset"] == "pro"
    assert payload["allocation"]["effective_model_preset"] == "pro"


def test_cost_command_reports_budget_exceeded(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["cost", "add a helper", "--workspace", str(tmp_path), "--max-cost-score", "1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["budget_exceeded"] is True
    assert payload["allocation"]["budget_exceeded"] is True


def test_cost_command_applies_scoped_model_override(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "cost",
            "add a helper",
            "--workspace",
            str(tmp_path),
            "--role-model",
            "coder=main:pro-coder",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    coder = next(
        assignment
        for assignment in payload["allocation"]["assignments"]
        if assignment["agent_id"] == "coder"
    )
    assert coder["model_id"] == "main:pro-coder"
    assert coder["reason"] == "explicit model override for coder"


def test_cost_command_prints_tables(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["cost", "plan repository architecture", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Cost preview" in result.output
    assert "Assignment cost" in result.output
