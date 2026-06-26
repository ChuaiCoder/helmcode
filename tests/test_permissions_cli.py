from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.safety.permission_store import PermissionStore
from helmcode.tools.shell import ShellTool


def test_permissions_add_list_remove_and_clear(tmp_path: Path) -> None:
    runner = CliRunner()

    add = runner.invoke(
        app,
        ["permissions", "add", "git push", "--workspace", str(tmp_path), "--yes", "--json"],
    )
    assert add.exit_code == 0
    assert json.loads(add.output)["allowed_commands"] == ["git push"]

    listing = runner.invoke(app, ["permissions", "--workspace", str(tmp_path), "--json"])
    assert listing.exit_code == 0
    assert json.loads(listing.output)["allowed_commands"] == ["git push"]

    remove = runner.invoke(
        app,
        ["permissions", "remove", "git push", "--workspace", str(tmp_path), "--yes", "--json"],
    )
    assert remove.exit_code == 0
    assert json.loads(remove.output)["allowed_commands"] == []

    PermissionStore.for_workspace(tmp_path).add("npm publish")
    clear = runner.invoke(app, ["permissions", "clear", "--workspace", str(tmp_path), "--yes", "--json"])
    assert clear.exit_code == 0
    assert json.loads(clear.output)["removed"] == 1


def test_permissions_refuse_blocked_destructive_prefix(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["permissions", "add", "git reset --hard", "--workspace", str(tmp_path), "--yes"],
    )

    assert result.exit_code != 0
    assert "refusing to store blocked command prefix" in result.output
    assert PermissionStore.for_workspace(tmp_path).allowed_commands == []


def test_shell_tool_uses_workspace_permissions(tmp_path: Path) -> None:
    PermissionStore.for_workspace(tmp_path).add("git push")

    result = ShellTool().run(
        {
            "root_path": tmp_path,
            "command": "git push --dry-run",
            "permission_mode": "auto",
        }
    )

    assert "returncode" in result.data
    assert "risk" not in result.data


def test_shell_tool_still_blocks_destructive_allowed_prefix(tmp_path: Path) -> None:
    store = PermissionStore.for_workspace(tmp_path)
    store.allowed_commands = ["git reset"]
    store._write()

    result = ShellTool().run(
        {
            "root_path": tmp_path,
            "command": "git reset --hard",
            "permission_mode": "auto",
        }
    )

    assert result.ok is False
    assert result.data["risk"] == "blocked"
