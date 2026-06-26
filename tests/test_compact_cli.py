from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.memory.session_compaction import SessionCompactionStore
from helmcode.memory.session_store import SessionStore


def test_compact_command_writes_markdown_and_index(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})
    store.record(
        "session-a",
        "task_allocated",
        {
            "detected_task_type": "code_patch",
            "complexity": "low",
            "strategy": "quota-saving direct path",
            "baseline_cost_score": 8,
            "selected_cost_score": 5,
            "estimated_savings_score": 3,
            "assignments": [
                {
                    "agent_id": "planner",
                    "task_type": "plan",
                    "required": True,
                    "model_id": "main:planner",
                    "estimated_cost_score": 2,
                },
                {
                    "agent_id": "coder",
                    "task_type": "code_patch",
                    "required": True,
                    "model_id": "main:coder",
                    "estimated_cost_score": 3,
                },
            ],
        },
    )
    store.record(
        "session-a",
        "model_called",
        {
            "role": "planning",
            "task_type": "plan",
            "model_id": "main:planner",
            "routing_mode": "quota",
            "usage": {"total_tokens": 120, "cached_tokens": 20},
        },
    )
    store.record("session-a", "plan_created", {"content": "1. Edit tests\n2. Run pytest"})
    store.record("session-a", "patch_created", {"files": ["tests/test_app.py"]})
    store.record("session-a", "command_result", {"command": "pytest", "ok": True, "output": "passed"})

    result = CliRunner().invoke(
        app,
        ["compact", "session-a", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["session_id"] == "session-a"
    assert payload["event_count"] == 6
    compaction_path = Path(payload["path"])
    assert compaction_path.exists()
    text = compaction_path.read_text(encoding="utf-8")
    assert "# Helmcode Session Compaction" in text
    assert "planner (plan, required) -> main:planner cost=2" in text
    assert "coding/code_patch -> main:coder" not in text
    assert "tests/test_app.py" in text
    assert "pytest ok=True" in text
    recorded_events = SessionStore(tmp_path, enable_structured_logging=False).list_events("session-a")
    assert recorded_events[-1].event_type == "session_compacted"


def test_compact_command_defaults_to_latest_session_and_can_show_text(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "first"})
    store.record("session-b", "user_message", {"content": "second"})

    result = CliRunner().invoke(
        app,
        ["compact", "--workspace", str(tmp_path), "--json", "--show-text"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["session_id"] == "session-b"
    assert "Task: second" in payload["text"]


def test_compact_command_lists_compactions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})
    SessionCompactionStore(tmp_path).compact("session-a")

    result = CliRunner().invoke(
        app,
        ["compact", "--workspace", str(tmp_path), "--list", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["session_id"] == "session-a"
    assert Path(payload[0]["path"]).exists()


def test_compact_unknown_session_fails(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["compact", "missing-session", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "no events found for session" in result.output
