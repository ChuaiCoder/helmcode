from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.models.quota import QuotaLedger


def test_quota_history_outputs_json_records(tmp_path: Path) -> None:
    ledger = QuotaLedger.for_workspace(tmp_path)
    ledger.record(
        model_id="main:planner",
        role="planning",
        task_type="plan",
        unit="request",
        amount=1,
        session_id="session-1",
        reason="selected for plan",
    )
    ledger.record(
        model_id="main:planner",
        role="planning",
        task_type="plan",
        unit="token",
        amount=42,
        session_id="session-1",
        reason="selected for plan",
    )

    result = CliRunner().invoke(
        app,
        ["quota", "history", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [record["unit"] for record in payload] == ["token", "request"]
    assert payload[0]["amount"] == 42
    assert payload[0]["session_id"] == "session-1"


def test_quota_history_filters_records(tmp_path: Path) -> None:
    ledger = QuotaLedger.for_workspace(tmp_path)
    ledger.record(model_id="main:planner", role="planning", task_type="plan", unit="token", amount=42)
    ledger.record(model_id="main:coder", role="coding", task_type="code_patch", unit="token", amount=80)

    result = CliRunner().invoke(
        app,
        [
            "quota",
            "history",
            "--workspace",
            str(tmp_path),
            "--model",
            "main:coder",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["model_id"] == "main:coder"


def test_quota_reset_removes_filtered_records(tmp_path: Path) -> None:
    ledger = QuotaLedger.for_workspace(tmp_path)
    ledger.record(model_id="main:planner", role="planning", task_type="plan", unit="request", amount=1)
    ledger.record(model_id="main:planner", role="planning", task_type="plan", unit="token", amount=42)

    result = CliRunner().invoke(
        app,
        ["quota", "reset", "--workspace", str(tmp_path), "--unit", "token", "--yes"],
    )

    assert result.exit_code == 0
    assert "Removed 1 quota ledger record" in result.output
    records = ledger.load()
    assert [(record.unit, record.amount) for record in records] == [("request", 1)]


def test_quota_without_subcommand_shows_status(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["quota", "--workspace", str(tmp_path)])

    assert result.exit_code == 0
    assert "Quota status" in result.output
