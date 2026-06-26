from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.core import config as config_module


def _isolate_user_config(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_module, "user_config_path", lambda: path)
    return path


def test_mcp_add_list_show_export_and_remove(monkeypatch, tmp_path: Path) -> None:
    _isolate_user_config(monkeypatch, tmp_path)
    runner = CliRunner()

    add = runner.invoke(
        app,
        [
            "mcp",
            "add",
            "filesystem",
            "--command",
            "python",
            "--arg",
            "-m",
            "--arg",
            "server",
            "--env",
            "API_KEY=${FILESYSTEM_API_KEY}",
            "--description",
            "filesystem tools",
            "--json",
        ],
    )
    listing = runner.invoke(app, ["mcp", "list", "--json"])
    show = runner.invoke(app, ["mcp", "show", "filesystem", "--json"])
    exported = runner.invoke(app, ["mcp", "export", "--format", "claude"])
    removed = runner.invoke(app, ["mcp", "remove", "filesystem", "--yes", "--json"])

    assert add.exit_code == 0
    assert json.loads(add.output)["env"] == {"API_KEY": "<redacted>"}
    assert listing.exit_code == 0
    assert json.loads(listing.output)[0]["id"] == "filesystem"
    assert show.exit_code == 0
    assert json.loads(show.output)["env"] == {"API_KEY": "<redacted>"}
    assert exported.exit_code == 0
    assert json.loads(exported.output)["mcpServers"]["filesystem"] == {
        "command": "python",
        "args": ["-m", "server"],
        "env": {"API_KEY": "${FILESYSTEM_API_KEY}"},
    }
    assert removed.exit_code == 0
    assert json.loads(removed.output) == {"server_id": "filesystem", "removed": True}


def test_mcp_http_server_and_doctor(monkeypatch, tmp_path: Path) -> None:
    _isolate_user_config(monkeypatch, tmp_path)
    runner = CliRunner()

    add = runner.invoke(
        app,
        [
            "mcp",
            "add",
            "remote",
            "--transport",
            "http",
            "--url",
            "http://127.0.0.1:9000/mcp",
            "--json",
        ],
    )
    doctor = runner.invoke(app, ["mcp", "doctor", "--json"])

    assert add.exit_code == 0
    assert json.loads(add.output)["transport"] == "http"
    assert doctor.exit_code == 0
    assert json.loads(doctor.output) == [
        {
            "id": "remote",
            "transport": "http",
            "ok": True,
            "details": "http://127.0.0.1:9000/mcp",
        }
    ]


def test_mcp_add_refuses_duplicate_without_force(monkeypatch, tmp_path: Path) -> None:
    _isolate_user_config(monkeypatch, tmp_path)
    runner = CliRunner()

    first = runner.invoke(app, ["mcp", "add", "server", "--command", "python"])
    second = runner.invoke(app, ["mcp", "add", "server", "--command", "python"])

    assert first.exit_code == 0
    assert second.exit_code != 0
    assert "already exists" in second.output


def test_mcp_stdio_requires_command(monkeypatch, tmp_path: Path) -> None:
    _isolate_user_config(monkeypatch, tmp_path)

    result = CliRunner().invoke(app, ["mcp", "add", "broken"])

    assert result.exit_code != 0
    assert "stdio MCP servers require command" in result.output
