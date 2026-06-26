from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app


def test_checkpoint_create_and_show_json(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("before\n", encoding="utf-8")

    create = CliRunner().invoke(
        app,
        ["checkpoint", "create", "before edit", "--workspace", str(tmp_path), "--json"],
    )

    assert create.exit_code == 0
    created = json.loads(create.output)
    assert created["label"] == "before edit"
    assert created["file_count"] == 1

    show = CliRunner().invoke(
        app,
        ["checkpoint", "show", created["id"], "--workspace", str(tmp_path), "--json"],
    )

    assert show.exit_code == 0
    payload = json.loads(show.output)
    assert payload["files"] == ["app.py"]


def test_checkpoint_restore_json_restores_content(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("before\n", encoding="utf-8")
    create = CliRunner().invoke(
        app,
        ["checkpoint", "create", "--workspace", str(tmp_path), "--json"],
    )
    checkpoint_id = json.loads(create.output)["id"]

    target.write_text("after\n", encoding="utf-8")
    restore = CliRunner().invoke(
        app,
        ["checkpoint", "restore", checkpoint_id, "--workspace", str(tmp_path), "--yes", "--json"],
    )

    assert restore.exit_code == 0
    payload = json.loads(restore.output)
    assert payload["restored_files"] == ["app.py"]
    assert target.read_text(encoding="utf-8") == "before\n"


def test_top_level_restore_alias_accepts_path_filter(tmp_path: Path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text("a1\n", encoding="utf-8")
    second.write_text("b1\n", encoding="utf-8")
    create = CliRunner().invoke(
        app,
        ["checkpoint", "create", "--workspace", str(tmp_path), "--json"],
    )
    checkpoint_id = json.loads(create.output)["id"]

    first.write_text("a2\n", encoding="utf-8")
    second.write_text("b2\n", encoding="utf-8")
    restore = CliRunner().invoke(
        app,
        [
            "restore",
            checkpoint_id,
            "--workspace",
            str(tmp_path),
            "--path",
            "a.py",
            "--yes",
            "--json",
        ],
    )

    assert restore.exit_code == 0
    assert json.loads(restore.output)["restored_files"] == ["a.py"]
    assert first.read_text(encoding="utf-8") == "a1\n"
    assert second.read_text(encoding="utf-8") == "b2\n"


def test_checkpoint_delete_json(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("code\n", encoding="utf-8")
    create = CliRunner().invoke(
        app,
        ["checkpoint", "create", "--workspace", str(tmp_path), "--json"],
    )
    checkpoint_id = json.loads(create.output)["id"]

    delete = CliRunner().invoke(
        app,
        ["checkpoint", "delete", checkpoint_id, "--workspace", str(tmp_path), "--yes", "--json"],
    )
    listing = CliRunner().invoke(app, ["checkpoint", "--workspace", str(tmp_path), "--json"])

    assert delete.exit_code == 0
    assert json.loads(delete.output) == {"checkpoint_id": checkpoint_id, "deleted": True}
    assert json.loads(listing.output) == []
