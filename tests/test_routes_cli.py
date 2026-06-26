from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app


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
