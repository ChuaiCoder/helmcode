from __future__ import annotations

from pathlib import Path

from helmcode.cli.commands import chat


def test_interactive_state_commands_update_mode_routing_and_model(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)

    assert chat.handle_interactive_line("/mode run", state) is True
    assert chat.handle_interactive_line("/routing fixed", state) is True
    assert chat.handle_interactive_line("/model main:coder", state) is True
    assert chat.handle_interactive_line("/budget 5", state) is True
    assert chat.handle_interactive_line("/yes on", state) is True
    assert chat.handle_interactive_line("/tests off", state) is True

    assert state.action_mode == "run"
    assert state.routing_mode == "fixed"
    assert state.forced_model == "main:coder"
    assert state.max_cost_score == 5
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
            "max_cost_score": None,
        }
    ]


def test_run_command_passes_session_flags(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        action_mode="run",
        routing_mode="quota",
        forced_model="main:coder",
        max_cost_score=6,
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
            "max_cost_score": 6,
        }
    ]


def test_agents_command_builds_allocation(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        routing_mode="fixed",
        forced_model="main:coder",
        max_cost_score=4,
    )
    calls: list[dict[str, object]] = []

    class FakeAllocation:
        pass

    def record_build(**kwargs):
        calls.append(kwargs)
        return FakeAllocation()

    printed: list[object] = []

    monkeypatch.setattr(chat.agents, "build_allocation", record_build)
    monkeypatch.setattr(chat.agents, "print_allocation", printed.append)

    assert chat.handle_interactive_line("/agents split this work", state) is True

    assert calls == [
        {
            "task": "split this work",
            "workspace": tmp_path,
            "routing": "fixed",
            "model": "main:coder",
            "include_repair": False,
            "max_cost_score": 4,
        }
    ]
    assert isinstance(printed[0], FakeAllocation)


def test_tool_command_passes_json_to_tools_cli(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_run_tool(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.tools, "run_tool", record_run_tool)

    assert chat.handle_interactive_line('/tool read_file {"path":"README.md"}', state) is True

    assert calls == [
        {
            "tool_name": "read_file",
            "input_json": '{"path":"README.md"}',
            "workspace": tmp_path,
        }
    ]


def test_exit_command_stops_session(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)

    assert chat.handle_interactive_line("/exit", state) is False
