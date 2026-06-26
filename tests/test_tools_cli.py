from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.memory.session_store import SessionStore
from helmcode.tools.registry import default_tool_registry


def test_default_tool_registry_contains_core_tools() -> None:
    registry = default_tool_registry()

    assert {
        "diagnostics",
        "git_diff",
        "git_status",
        "list_files",
        "read_file",
        "run_tests",
        "search_code",
        "shell",
        "write_patch",
    }.issubset(set(registry.names()))


def test_tools_list_json(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["tools", "list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert any(tool["name"] == "read_file" and tool["risk_level"] == "low" for tool in payload)


def test_tools_run_read_file_records_audit_event(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["tools", "run", "read_file", '{"path":"README.md"}', "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert "1: hello" in payload["content"]
    events = SessionStore(tmp_path).list_events("tool-cli")
    assert events[-1].event_type == "tool_result"
    assert events[-1].payload["tool"] == "read_file"


def test_tools_run_accepts_repeatable_params(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("first\nsecond\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "tools",
            "run",
            "read_file",
            "--workspace",
            str(tmp_path),
            "--param",
            "path=README.md",
            "--param",
            "end_line=1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "1: first" in payload["content"]
    assert "second" not in payload["content"]


def test_tools_run_refuses_sensitive_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["tools", "run", "read_file", '{"path":".env"}', "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "Refusing" in payload["content"]
    assert "secret" not in payload["content"]


def test_tools_run_shell_uses_permission_policy(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "tools",
            "run",
            "shell",
            '{"command":"git reset --hard"}',
            "--workspace",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "blocked" in payload["data"]["risk"]
