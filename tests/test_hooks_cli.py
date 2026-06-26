from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.memory.hooks import HookRunner, HookStore


def test_hooks_cli_add_list_show_toggle_and_clear(tmp_path: Path) -> None:
    runner = CliRunner()

    add = runner.invoke(
        app,
        [
            "hooks",
            "add",
            "pre_plan",
            "python -c \"print('hook')\"",
            "--id",
            "precheck",
            "--required",
            "--timeout",
            "5",
            "--workspace",
            str(tmp_path),
            "--json",
        ],
    )
    assert add.exit_code == 0
    added = json.loads(add.output)
    assert added["id"] == "precheck"
    assert added["required"] is True
    assert added["timeout_seconds"] == 5

    listing = runner.invoke(app, ["hooks", "--workspace", str(tmp_path), "--json"])
    assert listing.exit_code == 0
    assert json.loads(listing.output)[0]["id"] == "precheck"

    shown = runner.invoke(
        app,
        ["hooks", "show", "precheck", "--workspace", str(tmp_path), "--json"],
    )
    assert shown.exit_code == 0
    assert json.loads(shown.output)["event"] == "pre_plan"

    disabled = runner.invoke(
        app,
        ["hooks", "disable", "precheck", "--workspace", str(tmp_path), "--json"],
    )
    assert disabled.exit_code == 0
    assert json.loads(disabled.output)["changed"] is True
    assert HookStore(tmp_path).get("precheck").enabled is False

    enabled = runner.invoke(
        app,
        ["hooks", "enable", "precheck", "--workspace", str(tmp_path), "--json"],
    )
    assert enabled.exit_code == 0
    assert json.loads(enabled.output)["changed"] is True
    assert HookStore(tmp_path).get("precheck").enabled is True

    optional = runner.invoke(
        app,
        ["hooks", "optional", "precheck", "--workspace", str(tmp_path), "--json"],
    )
    assert optional.exit_code == 0
    assert HookStore(tmp_path).get("precheck").required is False

    removed = runner.invoke(
        app,
        ["hooks", "remove", "precheck", "--workspace", str(tmp_path), "--yes", "--json"],
    )
    assert removed.exit_code == 0
    assert json.loads(removed.output)["removed"] is True

    HookStore(tmp_path).add(event="post_test", command="python -c \"print('test')\"")
    cleared = runner.invoke(
        app,
        ["hooks", "clear", "--workspace", str(tmp_path), "--yes", "--json"],
    )
    assert cleared.exit_code == 0
    assert json.loads(cleared.output)["removed"] == 1


def test_hooks_cli_lists_supported_events() -> None:
    result = CliRunner().invoke(app, ["hooks", "events", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [item["event"] for item in payload] == [
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
        "pre_plan",
        "post_plan",
        "pre_patch",
        "post_patch",
        "post_apply",
        "post_test",
    ]


def test_hook_runner_passes_event_payload_on_stdin(tmp_path: Path) -> None:
    HookStore(tmp_path).add(
        event="pre_plan",
        command='python -c "import sys,json; print(json.load(sys.stdin)[\'event\'])"',
    )

    results = HookRunner(tmp_path, permission_mode="suggest").run_event(
        "pre_plan",
        session_id="session-a",
        payload={"task": "plan work"},
    )

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].output == "pre_plan"
    assert results[0].event_payload["session_id"] == "session-a"
    assert results[0].event_payload["payload"] == {"task": "plan work"}


def test_hook_runner_returns_timeout_as_failed_result(tmp_path: Path) -> None:
    HookStore(tmp_path).add(
        event="pre_plan",
        command='python -c "import time; time.sleep(2)"',
        timeout_seconds=1,
    )

    results = HookRunner(tmp_path, permission_mode="suggest").run_event("pre_plan")

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].data["timed_out"] is True
    assert "timed out" in results[0].output
