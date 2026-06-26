from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app


def test_skills_list_includes_builtin(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["skills", "list", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["id"] == "codingplan-routing"
    assert payload[0]["source"] == "builtin"


def test_skills_add_match_show_and_delete(tmp_path: Path) -> None:
    add = CliRunner().invoke(
        app,
        [
            "skills",
            "add",
            "api-review",
            "--workspace",
            str(tmp_path),
            "--description",
            "API review guidance",
            "--trigger",
            "api",
            "--instructions",
            "Check API compatibility.",
            "--json",
        ],
    )

    assert add.exit_code == 0
    assert json.loads(add.output)["id"] == "api-review"

    match = CliRunner().invoke(
        app,
        ["skills", "match", "change api response", "--workspace", str(tmp_path), "--json"],
    )
    show = CliRunner().invoke(
        app,
        ["skills", "show", "api-review", "--workspace", str(tmp_path), "--json"],
    )
    delete = CliRunner().invoke(
        app,
        ["skills", "delete", "api-review", "--workspace", str(tmp_path), "--yes", "--json"],
    )

    assert match.exit_code == 0
    assert [item["id"] for item in json.loads(match.output)] == ["api-review"]
    assert show.exit_code == 0
    assert json.loads(show.output)["instructions"] == "Check API compatibility."
    assert delete.exit_code == 0
    assert json.loads(delete.output) == {"skill_id": "api-review", "deleted": True}


def test_skills_add_from_instruction_file(tmp_path: Path) -> None:
    instructions = tmp_path / "instructions.md"
    instructions.write_text("Use repository-specific review steps.", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "skills",
            "add",
            "repo-review",
            "--workspace",
            str(tmp_path),
            "--trigger",
            "review",
            "--instructions-file",
            str(instructions),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["instructions"] == "Use repository-specific review steps."
