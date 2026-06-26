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


def test_cost_command_reports_budget_exceeded(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["cost", "add a helper", "--workspace", str(tmp_path), "--max-cost-score", "1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["budget_exceeded"] is True
    assert payload["allocation"]["budget_exceeded"] is True


def test_cost_command_prints_tables(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["cost", "plan repository architecture", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Cost preview" in result.output
    assert "Assignment cost" in result.output
