from __future__ import annotations

from pathlib import Path

from helmcode.cli.commands import chat


def test_interactive_state_commands_update_mode_routing_and_model(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)

    assert chat.handle_interactive_line("/mode run", state) is True
    assert chat.handle_interactive_line("/routing fixed", state) is True
    assert chat.handle_interactive_line("/model main:coder", state) is True
    assert chat.handle_interactive_line("/yes on", state) is True
    assert chat.handle_interactive_line("/tests off", state) is True

    assert state.action_mode == "run"
    assert state.routing_mode == "fixed"
    assert state.forced_model == "main:coder"
    assert state.yes is True
    assert state.run_tests is False


def test_bare_prompt_uses_current_mode(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path, action_mode="recommend", forced_model="main:coder")
    calls: list[dict[str, object]] = []

    def record_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.run, "run_task", record_run)

    assert chat.handle_interactive_line("implement feature", state) is True

    assert calls == [
        {
            "task": "implement feature",
            "workspace": tmp_path,
            "yes": False,
            "no_tests": False,
            "routing": "recommend",
            "model": "main:coder",
        }
    ]


def test_run_command_passes_session_flags(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        action_mode="run",
        routing_mode="quota",
        forced_model="main:coder",
        yes=True,
        run_tests=False,
    )
    calls: list[dict[str, object]] = []

    def record_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.run, "run_task", record_run)

    assert chat.handle_interactive_line("/run fix tests", state) is True

    assert calls == [
        {
            "task": "fix tests",
            "workspace": tmp_path,
            "yes": True,
            "no_tests": True,
            "routing": "quota",
            "model": "main:coder",
        }
    ]


def test_exit_command_stops_session(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)

    assert chat.handle_interactive_line("/exit", state) is False
