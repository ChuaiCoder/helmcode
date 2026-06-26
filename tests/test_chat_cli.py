from __future__ import annotations

from pathlib import Path

from helmcode.cli.commands import chat


def test_interactive_state_commands_update_mode_routing_and_model(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)

    assert chat.handle_interactive_line("/mode run", state) is True
    assert chat.handle_interactive_line("/routing fixed", state) is True
    assert chat.handle_interactive_line("/model main:coder", state) is True
    assert chat.handle_interactive_line("/budget 5", state) is True
    assert chat.handle_interactive_line("/cache off", state) is True
    assert chat.handle_interactive_line("/yes on", state) is True
    assert chat.handle_interactive_line("/tests off", state) is True

    assert state.action_mode == "run"
    assert state.routing_mode == "fixed"
    assert state.forced_model == "main:coder"
    assert state.max_cost_score == 5
    assert state.preplan_cache is False
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
            "no_preplan_cache": False,
        }
    ]


def test_run_command_passes_session_flags(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        action_mode="run",
        routing_mode="quota",
        forced_model="main:coder",
        max_cost_score=6,
        preplan_cache=False,
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
            "no_preplan_cache": True,
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


def test_context_command_previews_context(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_context(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.context, "context_cmd", record_context)

    assert chat.handle_interactive_line("/context explain @README.md", state) is True

    assert calls == [
        {
            "task": "explain @README.md",
            "workspace": tmp_path,
            "show_text": False,
            "output_json": False,
            "max_file_chars": 4_000,
            "max_explicit_files": 8,
        }
    ]


def test_cost_command_previews_cost(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        routing_mode="recommend",
        forced_model="main:coder",
        max_cost_score=6,
    )
    calls: list[dict[str, object]] = []

    def record_cost(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.cost, "cost_cmd", record_cost)

    assert chat.handle_interactive_line("/cost plan @README.md", state) is True

    assert calls == [
        {
            "task": "plan @README.md",
            "workspace": tmp_path,
            "routing": "quota",
            "model": "main:coder",
            "include_repair": False,
            "max_cost_score": 6,
            "max_file_chars": 4_000,
            "max_explicit_files": 8,
            "output_json": False,
        }
    ]


def test_routes_command_compares_current_session_routing(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        forced_model="main:coder",
        max_cost_score=7,
    )
    calls: list[dict[str, object]] = []

    def record_routes(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.routes, "routes_cmd", record_routes)

    assert chat.handle_interactive_line("/routes add tests", state) is True

    assert calls == [
        {
            "task": "add tests",
            "workspace": tmp_path,
            "model": "main:coder",
            "include_repair": False,
            "max_cost_score": 7,
            "output_json": False,
        }
    ]


def test_savings_command_reports_history(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_savings(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.savings, "savings_cmd", record_savings)

    assert chat.handle_interactive_line("/savings", state) is True

    assert calls == [
        {
            "workspace": tmp_path,
            "limit": None,
            "output_json": False,
        }
    ]


def test_allocations_command_reports_history(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_allocations(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.allocations, "allocations_cmd", record_allocations)

    assert chat.handle_interactive_line("/allocations session-a", state) is True
    assert chat.handle_interactive_line("/plans", state) is True

    assert calls == [
        {
            "workspace": tmp_path,
            "session_id": "session-a",
            "limit": 20,
            "output_json": False,
        },
        {
            "workspace": tmp_path,
            "session_id": None,
            "limit": 20,
            "output_json": False,
        },
    ]


def test_compact_command_compacts_session(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_compact(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.compact, "compact_cmd", record_compact)

    assert chat.handle_interactive_line("/compact session-a", state) is True

    assert calls == [
        {
            "session_id": "session-a",
            "workspace": tmp_path,
            "list_compactions": False,
            "show_text": False,
            "output_json": False,
        }
    ]


def test_tokens_command_reports_usage(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_tokens(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.tokens, "tokens_cmd", record_tokens)

    assert chat.handle_interactive_line("/tokens session-a", state) is True

    assert calls == [
        {
            "workspace": tmp_path,
            "session_id": "session-a",
            "limit": None,
            "output_json": False,
        }
    ]


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


def test_quota_history_command_uses_quota_cli(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_history(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.quota, "history_quota", record_history)

    assert chat.handle_interactive_line("/quota history", state) is True

    assert calls == [
        {
            "workspace": tmp_path,
            "model_id": None,
            "unit": None,
            "role": None,
            "limit": 20,
            "output_json": False,
        }
    ]


def test_quota_reset_requires_interactive_confirmation_word(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_reset(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.quota, "reset_quota", record_reset)

    assert chat.handle_interactive_line("/quota reset", state) is True
    assert calls == []

    assert chat.handle_interactive_line("/quota reset yes", state) is True
    assert calls == [
        {
            "workspace": tmp_path,
            "model_id": None,
            "unit": None,
            "role": None,
            "yes": True,
        }
    ]


def test_exit_command_stops_session(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)

    assert chat.handle_interactive_line("/exit", state) is False
