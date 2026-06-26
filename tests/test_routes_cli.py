from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app


def _write_budget_status(workspace: Path, *, key: str, selected_cost_score: int) -> None:
    budget_dir = workspace / ".helmcode"
    budget_dir.mkdir(parents=True, exist_ok=True)
    (budget_dir / "coding_plan_budget.json").write_text(
        json.dumps(
            {
                "version": 1,
                "budgets": {
                    key: {
                        "allocation_count": 1,
                        "baseline_cost_score": selected_cost_score,
                        "selected_cost_score": selected_cost_score,
                        "estimated_savings_score": 0,
                        "blocked_count": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_routes_command_compares_fixed_and_quota_json(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["routes", "add tests", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["task"] == "add tests"
    assert [route["route"] for route in payload["routes"]] == ["fixed", "quota"]
    assert payload["routes"][0]["ok"] is True
    assert payload["routes"][1]["ok"] is True
    assert payload["routes"][0]["summary"]["selected_cost_score"] >= 1
    assert payload["routes"][1]["selected_cost_delta_vs_fixed"] is not None
    assert isinstance(payload["routes"][1]["assignment_route"], list)
    assert payload["best_route"] == "quota"


def test_routes_command_exposes_auto_effective_preset(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "routes",
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
    quota_route = next(route for route in payload["routes"] if route["route"] == "quota")
    assert payload["model_preset"] == "auto"
    assert quota_route["model_preset"] == "auto"
    assert quota_route["effective_model_preset"] == "pro"
    assert quota_route["summary"]["effective_model_preset"] == "pro"


def test_routes_command_compares_all_presets_json(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "routes",
            "refactor the whole project architecture and implement a large routing change",
            "--workspace",
            str(tmp_path),
            "--compare-presets",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["compare_presets"] is True
    assert payload["presets_compared"] == ["auto", "economy", "balanced", "pro"]
    assert [route["route"] for route in payload["routes"]] == [
        "fixed",
        "quota:auto",
        "quota:economy",
        "quota:balanced",
        "quota:pro",
    ]
    routes = {route["route"]: route for route in payload["routes"]}
    assert routes["quota:auto"]["model_preset"] == "auto"
    assert routes["quota:auto"]["effective_model_preset"] == "pro"
    assert routes["quota:economy"]["summary"]["model_preset"] == "economy"
    assert routes["quota:balanced"]["summary"]["effective_model_preset"] == "balanced"
    assert routes["quota:pro"]["summary"]["effective_model_preset"] == "pro"
    assert payload["best_route"] in routes


def test_routes_command_previews_session_budget_warning(tmp_path: Path) -> None:
    _write_budget_status(tmp_path, key="chat", selected_cost_score=5)

    result = CliRunner().invoke(
        app,
        [
            "routes",
            "add tests",
            "--workspace",
            str(tmp_path),
            "--session-budget-score",
            "12",
            "--budget-key",
            "chat",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    quota_route = next(route for route in payload["routes"] if route["route"] == "quota")
    assert payload["budget_key"] == "chat"
    assert payload["current_session_selected_cost_score"] == 5
    assert quota_route["session_budget"] == {
        "budget_key": "chat",
        "session_budget_score": 12,
        "current_selected_cost_score": 5,
        "selected_cost_score": 6,
        "projected_selected_cost_score": 11,
        "remaining_score_after": 1,
        "warning_threshold_score": 10,
        "budget_warning": True,
        "budget_exceeded": False,
    }
    assert quota_route["summary"]["session_budget_warning"] is True
    assert quota_route["summary"]["session_budget_exceeded"] is False
    assert payload["best_route"] == "quota"


def test_routes_command_excludes_session_budget_exceeded_routes_from_best(tmp_path: Path) -> None:
    _write_budget_status(tmp_path, key="chat", selected_cost_score=5)

    result = CliRunner().invoke(
        app,
        [
            "routes",
            "add tests",
            "--workspace",
            str(tmp_path),
            "--session-budget-score",
            "10",
            "--budget-key",
            "chat",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["best_route"] is None
    assert all(route["summary"]["session_budget_exceeded"] for route in payload["routes"])


def test_routes_command_includes_forced_model_route(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "routes",
            "add tests",
            "--workspace",
            str(tmp_path),
            "--model",
            "main:forced",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    routes = {route["route"]: route for route in payload["routes"]}
    assert set(routes) == {"fixed", "quota", "forced"}
    assert routes["forced"]["forced_model"] == "main:forced"
    assert all("main:forced" in item for item in routes["forced"]["assignment_route"])


def test_routes_command_applies_scoped_model_override(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "routes",
            "add tests",
            "--workspace",
            str(tmp_path),
            "--role-model",
            "coder=main:pro-coder",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["model_overrides"] == {"coder": "main:pro-coder"}
    quota_route = next(route for route in payload["routes"] if route["route"] == "quota")
    assert "coder=main:pro-coder" in quota_route["assignment_route"]


def test_routes_command_prints_table(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["routes", "plan repository architecture", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Coding Plan route comparison" in result.output
    assert "fixed" in result.output
    assert "quota" in result.output
