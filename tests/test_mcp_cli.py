from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.core import config as config_module
from helmcode.memory.session_store import SessionStore


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


def test_mcp_stdio_tools_and_call_run_real_json_rpc(monkeypatch, tmp_path: Path) -> None:
    _isolate_user_config(monkeypatch, tmp_path)
    server_path = _write_fake_mcp_server(tmp_path)
    runner = CliRunner()

    add = runner.invoke(
        app,
        [
            "mcp",
            "add",
            "fake",
            "--command",
            sys.executable,
            "--arg",
            str(server_path),
            "--json",
        ],
    )
    tools = runner.invoke(app, ["mcp", "tools", "fake", "--json"])
    called = runner.invoke(
        app,
        [
            "mcp",
            "call",
            "fake",
            "echo",
            '{"message":"hello"}',
            "--workspace",
            str(tmp_path),
            "--json",
        ],
    )

    assert add.exit_code == 0
    assert tools.exit_code == 0
    assert json.loads(tools.output)[0]["name"] == "echo"
    assert called.exit_code == 0
    payload = json.loads(called.output)
    assert payload["ok"] is True
    assert payload["content"] == "hello"
    assert payload["data"]["result"]["content"][0]["text"] == "hello"
    events = SessionStore(tmp_path).list_events("mcp-cli")
    assert events[-1].event_type == "mcp_tool_result"
    assert events[-1].payload["tool"] == "echo"


def test_mcp_call_rejects_non_stdio_runtime(monkeypatch, tmp_path: Path) -> None:
    _isolate_user_config(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        app,
        [
            "mcp",
            "add",
            "remote",
            "--transport",
            "http",
            "--url",
            "http://127.0.0.1:9000/mcp",
        ],
    )

    result = runner.invoke(app, ["mcp", "call", "remote", "tool", "{}"])

    assert result.exit_code != 0
    assert "supports stdio only" in result.output


def test_mcp_tools_times_out_when_server_does_not_respond(monkeypatch, tmp_path: Path) -> None:
    _isolate_user_config(monkeypatch, tmp_path)
    server_path = tmp_path / "hanging_mcp_server.py"
    server_path.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    runner = CliRunner()
    runner.invoke(
        app,
        [
            "mcp",
            "add",
            "hang",
            "--command",
            sys.executable,
            "--arg",
            str(server_path),
        ],
    )

    result = runner.invoke(app, ["mcp", "tools", "hang", "--timeout", "1"])

    assert result.exit_code != 0
    assert "timed out" in result.output


def _write_fake_mcp_server(tmp_path: Path) -> Path:
    server_path = tmp_path / "fake_mcp_server.py"
    server_path.write_text(
        r'''
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "echo a message",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    },
                }
            ]
        }
    elif method == "tools/call":
        text = message.get("params", {}).get("arguments", {}).get("message", "")
        result = {"content": [{"type": "text", "text": text}]}
    else:
        response = {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": "unknown method"},
        }
        print(json.dumps(response), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
''',
        encoding="utf-8",
    )
    return server_path
