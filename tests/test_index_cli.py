from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app


def test_index_build_and_changed_json(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('one')\n", encoding="utf-8")

    build = CliRunner().invoke(app, ["index", "build", "--workspace", str(tmp_path), "--json"])

    assert build.exit_code == 0
    payload = json.loads(build.output)
    assert payload["current_file_count"] == 2
    assert payload["cached_file_count"] == 2
    assert sorted(payload["changed_files"]) == ["app.py", "pyproject.toml"]

    (tmp_path / "app.py").write_text("print('two')\n", encoding="utf-8")
    changed = CliRunner().invoke(app, ["index", "changed", "--workspace", str(tmp_path), "--json"])

    assert changed.exit_code == 0
    assert json.loads(changed.output) == ["app.py"]


def test_index_status_reports_project_metadata(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"echo ok"},"dependencies":{}}',
        encoding="utf-8",
    )

    status = CliRunner().invoke(app, ["index", "--workspace", str(tmp_path), "--json"])

    assert status.exit_code == 0
    payload = json.loads(status.output)
    assert payload["languages"] == ["JavaScript"]
    assert payload["test_commands"] == ["npm test"]
