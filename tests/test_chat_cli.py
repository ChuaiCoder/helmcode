from __future__ import annotations

from pathlib import Path

from helmcode.cli.commands import chat


def test_interactive_state_commands_update_mode_routing_and_model(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)

    assert chat.handle_interactive_line("/mode run", state) is True
    assert chat.handle_interactive_line("/routing fixed", state) is True
    assert chat.handle_interactive_line("/preset pro", state) is True
    assert chat.handle_interactive_line("/model main:coder", state) is True
    assert chat.handle_interactive_line("/role-model coding=main:pro-coder", state) is True
    assert chat.handle_interactive_line("/budget 5", state) is True
    assert chat.handle_interactive_line("/session-budget 12", state) is True
    assert chat.handle_interactive_line("/session-budget key chat", state) is True
    assert chat.handle_interactive_line("/cache off", state) is True
    assert chat.handle_interactive_line("/yes on", state) is True
    assert chat.handle_interactive_line("/tests off", state) is True

    assert state.action_mode == "run"
    assert state.routing_mode == "fixed"
    assert state.model_preset == "pro"
    assert state.forced_model == "main:coder"
    assert state.model_overrides == {"coding": "main:pro-coder"}
    assert state.max_cost_score == 5
    assert state.session_budget_score == 12
    assert state.budget_key == "chat"
    assert state.preplan_cache is False
    assert state.yes is True
    assert state.run_tests is False


def test_role_model_command_manages_scoped_overrides(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)

    assert chat.handle_interactive_line("/role-model coder main:pro-coder", state) is True
    assert chat.handle_interactive_line("/role-model review=main:review-pro", state) is True
    assert state.model_overrides == {
        "coder": "main:pro-coder",
        "review": "main:review-pro",
    }

    assert chat.handle_interactive_line("/role-model clear coder", state) is True
    assert state.model_overrides == {"review": "main:review-pro"}

    assert chat.handle_interactive_line("/role-model clear", state) is True
    assert state.model_overrides is None


def test_pro_command_arms_next_task_preset(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path, action_mode="recommend")
    calls: list[dict[str, object]] = []

    def record_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.run, "run_task", record_run)

    assert chat.handle_interactive_line("/pro", state) is True
    assert state.next_model_preset == "pro"
    assert chat.handle_interactive_line("implement feature", state) is True

    assert calls[0]["preset"] == "pro"
    assert state.model_preset == "balanced"
    assert state.next_model_preset is None


def test_pro_command_runs_immediate_task_without_persisting(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        action_mode="run",
        model_preset="economy",
        next_model_preset="pro",
    )
    calls: list[dict[str, object]] = []

    def record_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.run, "run_task", record_run)

    assert chat.handle_interactive_line("/pro fix tests", state) is True

    assert calls[0]["task"] == "fix tests"
    assert calls[0]["preset"] == "pro"
    assert state.model_preset == "economy"
    assert state.next_model_preset is None


def test_pro_off_clears_armed_next_preset(tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path, next_model_preset="pro")

    assert chat.handle_interactive_line("/pro off", state) is True

    assert state.next_model_preset is None


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
            "preset": "balanced",
            "role_model": [],
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
        session_budget_score=12,
        budget_key="chat",
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
            "preset": "balanced",
            "role_model": [],
            "max_cost_score": 6,
            "session_budget_score": 12,
            "budget_key": "chat",
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
            "model_preset": "balanced",
            "model_overrides": None,
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
            "preset": "balanced",
            "role_model": [],
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
            "preset": "balanced",
            "role_model": [],
            "include_repair": False,
            "max_cost_score": 7,
            "session_budget_score": None,
            "budget_key": "default",
            "compare_presets": False,
            "output_json": False,
        }
    ]


def test_preset_routes_command_compares_presets(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        forced_model="main:coder",
        max_cost_score=7,
    )
    calls: list[dict[str, object]] = []

    def record_routes(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.routes, "routes_cmd", record_routes)

    assert chat.handle_interactive_line("/preset-routes add tests", state) is True

    assert calls == [
        {
            "task": "add tests",
            "workspace": tmp_path,
            "model": "main:coder",
            "preset": "balanced",
            "role_model": [],
            "include_repair": False,
            "max_cost_score": 7,
            "session_budget_score": None,
            "budget_key": "default",
            "compare_presets": True,
            "output_json": False,
        }
    ]


def test_routes_command_parses_compare_presets_flag(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_routes(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.routes, "routes_cmd", record_routes)

    assert chat.handle_interactive_line("/routes --compare-presets add tests", state) is True

    assert calls == [
        {
            "task": "add tests",
            "workspace": tmp_path,
            "model": None,
            "preset": "balanced",
            "role_model": [],
            "include_repair": False,
            "max_cost_score": None,
            "session_budget_score": None,
            "budget_key": "default",
            "compare_presets": True,
            "output_json": False,
        }
    ]


def test_retry_command_uses_current_session_flags(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        action_mode="plan",
        routing_mode="quota",
        forced_model="main:planner",
        max_cost_score=8,
        session_budget_score=12,
        budget_key="chat",
        preplan_cache=False,
        yes=True,
        run_tests=False,
    )
    calls: list[dict[str, object]] = []

    def record_retry(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.retry, "retry_cmd", record_retry)

    assert chat.handle_interactive_line("/retry session-a", state) is True

    assert calls == [
        {
            "session_id": "session-a",
            "workspace": tmp_path,
            "mode": "plan",
            "routing": "quota",
            "model": "main:planner",
            "preset": "balanced",
            "role_model": [],
            "max_cost_score": 8,
            "session_budget_score": 12,
            "budget_key": "chat",
            "yes": True,
            "no_tests": True,
            "no_preplan_cache": True,
        }
    ]


def test_new_command_resets_interactive_state(tmp_path: Path) -> None:
    state = chat.InteractiveState(
        workspace_path=tmp_path,
        action_mode="run",
        routing_mode="fixed",
        forced_model="main:coder",
        model_preset="pro",
        next_model_preset="pro",
        model_overrides={"coding": "main:pro-coder"},
        max_cost_score=5,
        session_budget_score=12,
        budget_key="chat",
        preplan_cache=False,
        yes=True,
        run_tests=False,
    )

    assert chat.handle_interactive_line("/new", state) is True

    assert state.action_mode == "recommend"
    assert state.routing_mode == "quota"
    assert state.forced_model is None
    assert state.model_preset == "balanced"
    assert state.next_model_preset is None
    assert state.model_overrides is None
    assert state.max_cost_score is None
    assert state.session_budget_score is None
    assert state.budget_key == "default"
    assert state.preplan_cache is True
    assert state.yes is False
    assert state.run_tests is True


def test_keys_command_shows_provider_status(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[dict[str, object]] = []

    def record_keys(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.keys, "keys_cmd", record_keys)

    assert chat.handle_interactive_line("/keys", state) is True

    assert calls == [
        {
            "config_path": None,
            "output_json": False,
        }
    ]


def test_permissions_command_routes_subcommands(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path, yes=True)
    calls: list[tuple[str, dict[str, object]]] = []

    def record_list(**kwargs):
        calls.append(("list", kwargs))

    def record_add(**kwargs):
        calls.append(("add", kwargs))

    def record_remove(**kwargs):
        calls.append(("remove", kwargs))

    def record_clear(**kwargs):
        calls.append(("clear", kwargs))

    monkeypatch.setattr(chat.permissions, "list_permissions", record_list)
    monkeypatch.setattr(chat.permissions, "add_permission", record_add)
    monkeypatch.setattr(chat.permissions, "remove_permission", record_remove)
    monkeypatch.setattr(chat.permissions, "clear_permissions", record_clear)

    assert chat.handle_interactive_line("/permissions", state) is True
    assert chat.handle_interactive_line("/permissions add git push", state) is True
    assert chat.handle_interactive_line("/permissions remove git push", state) is True
    assert chat.handle_interactive_line("/permissions clear", state) is True

    assert calls == [
        ("list", {"workspace": tmp_path, "output_json": False}),
        ("add", {"command_prefix": "git push", "workspace": tmp_path, "yes": True, "output_json": False}),
        ("remove", {"command_prefix": "git push", "workspace": tmp_path, "yes": True, "output_json": False}),
        ("clear", {"workspace": tmp_path, "yes": True, "output_json": False}),
    ]


def test_hooks_command_routes_subcommands(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path, yes=True)
    calls: list[tuple[str, dict[str, object]]] = []

    def record_list(**kwargs):
        calls.append(("list", kwargs))

    def record_events(**kwargs):
        calls.append(("events", kwargs))

    def record_add(**kwargs):
        calls.append(("add", kwargs))

    def record_show(**kwargs):
        calls.append(("show", kwargs))

    def record_disable(**kwargs):
        calls.append(("disable", kwargs))

    def record_enable(**kwargs):
        calls.append(("enable", kwargs))

    def record_require(**kwargs):
        calls.append(("require", kwargs))

    def record_optional(**kwargs):
        calls.append(("optional", kwargs))

    def record_remove(**kwargs):
        calls.append(("remove", kwargs))

    def record_clear(**kwargs):
        calls.append(("clear", kwargs))

    monkeypatch.setattr(chat.hooks_command, "list_hooks", record_list)
    monkeypatch.setattr(chat.hooks_command, "list_events", record_events)
    monkeypatch.setattr(chat.hooks_command, "add_hook", record_add)
    monkeypatch.setattr(chat.hooks_command, "show_hook", record_show)
    monkeypatch.setattr(chat.hooks_command, "disable_hook", record_disable)
    monkeypatch.setattr(chat.hooks_command, "enable_hook", record_enable)
    monkeypatch.setattr(chat.hooks_command, "require_hook", record_require)
    monkeypatch.setattr(chat.hooks_command, "optional_hook", record_optional)
    monkeypatch.setattr(chat.hooks_command, "remove_hook", record_remove)
    monkeypatch.setattr(chat.hooks_command, "clear_hooks", record_clear)

    assert chat.handle_interactive_line("/hooks", state) is True
    assert chat.handle_interactive_line("/hooks events", state) is True
    assert (
        chat.handle_interactive_line("/hooks add pre_plan --required python -m pytest -q", state)
        is True
    )
    assert chat.handle_interactive_line("/hooks show precheck", state) is True
    assert chat.handle_interactive_line("/hooks disable precheck", state) is True
    assert chat.handle_interactive_line("/hooks enable precheck", state) is True
    assert chat.handle_interactive_line("/hooks require precheck", state) is True
    assert chat.handle_interactive_line("/hooks optional precheck", state) is True
    assert chat.handle_interactive_line("/hooks remove precheck", state) is True
    assert chat.handle_interactive_line("/hooks clear", state) is True

    assert calls == [
        ("list", {"workspace": tmp_path, "event": None, "output_json": False}),
        ("events", {"output_json": False}),
        (
            "add",
            {
                "event": "pre_plan",
                "command": "python -m pytest -q",
                "hook_id": None,
                "required": True,
                "disabled": False,
                "timeout_seconds": 30,
                "description": "",
                "workspace": tmp_path,
                "output_json": False,
            },
        ),
        ("show", {"hook_id": "precheck", "workspace": tmp_path, "output_json": False}),
        ("disable", {"hook_id": "precheck", "workspace": tmp_path, "output_json": False}),
        ("enable", {"hook_id": "precheck", "workspace": tmp_path, "output_json": False}),
        ("require", {"hook_id": "precheck", "workspace": tmp_path, "output_json": False}),
        ("optional", {"hook_id": "precheck", "workspace": tmp_path, "output_json": False}),
        (
            "remove",
            {"hook_id": "precheck", "workspace": tmp_path, "yes": True, "output_json": False},
        ),
        ("clear", {"workspace": tmp_path, "yes": True, "output_json": False}),
    ]


def test_memory_command_routes_subcommands(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path, yes=True)
    calls: list[tuple[str, dict[str, object]]] = []

    def record_list(**kwargs):
        calls.append(("list", kwargs))

    def record_add(**kwargs):
        calls.append(("add", kwargs))

    def record_show(**kwargs):
        calls.append(("show", kwargs))

    def record_forget(**kwargs):
        calls.append(("forget", kwargs))

    def record_clear(**kwargs):
        calls.append(("clear", kwargs))

    monkeypatch.setattr(chat.memory_command, "list_memory", record_list)
    monkeypatch.setattr(chat.memory_command, "add_memory", record_add)
    monkeypatch.setattr(chat.memory_command, "show_memory", record_show)
    monkeypatch.setattr(chat.memory_command, "forget_memory", record_forget)
    monkeypatch.setattr(chat.memory_command, "clear_memory", record_clear)

    assert chat.handle_interactive_line("/memory", state) is True
    assert chat.handle_interactive_line("/memory add prefer quota routing", state) is True
    assert chat.handle_interactive_line("/memory show quota", state) is True
    assert chat.handle_interactive_line("/memory forget quota", state) is True
    assert chat.handle_interactive_line("/memory clear", state) is True

    assert calls == [
        ("list", {"workspace": tmp_path, "output_json": False}),
        ("add", {"text": "prefer quota routing", "memory_id": None, "workspace": tmp_path, "output_json": False}),
        ("show", {"memory_id": "quota", "workspace": tmp_path, "output_json": False}),
        ("forget", {"memory_id": "quota", "workspace": tmp_path, "yes": True, "output_json": False}),
        ("clear", {"workspace": tmp_path, "yes": True, "output_json": False}),
    ]


def test_commit_command_creates_local_commit(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path, yes=True)
    calls: list[dict[str, object]] = []

    def record_commit(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat.commit_command, "commit_cmd", record_commit)

    assert chat.handle_interactive_line("/commit Update docs", state) is True

    assert calls == [
        {
            "message": "Update docs",
            "workspace": tmp_path,
            "pathspecs": [],
            "dry_run": False,
            "yes": True,
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


def test_mcp_command_routes_runtime_subcommands(monkeypatch, tmp_path: Path) -> None:
    state = chat.InteractiveState(workspace_path=tmp_path)
    calls: list[tuple[str, dict[str, object]]] = []

    def record_list(**kwargs):
        calls.append(("list", kwargs))

    def record_tools(**kwargs):
        calls.append(("tools", kwargs))

    def record_call(**kwargs):
        calls.append(("call", kwargs))

    def record_resources(**kwargs):
        calls.append(("resources", kwargs))

    def record_resource(**kwargs):
        calls.append(("resource", kwargs))

    def record_prompts(**kwargs):
        calls.append(("prompts", kwargs))

    def record_prompt(**kwargs):
        calls.append(("prompt", kwargs))

    monkeypatch.setattr(chat.mcp, "list_mcp", record_list)
    monkeypatch.setattr(chat.mcp, "tools_mcp", record_tools)
    monkeypatch.setattr(chat.mcp, "call_mcp", record_call)
    monkeypatch.setattr(chat.mcp, "resources_mcp", record_resources)
    monkeypatch.setattr(chat.mcp, "resource_mcp", record_resource)
    monkeypatch.setattr(chat.mcp, "prompts_mcp", record_prompts)
    monkeypatch.setattr(chat.mcp, "prompt_mcp", record_prompt)

    assert chat.handle_interactive_line("/mcp", state) is True
    assert chat.handle_interactive_line("/mcp tools filesystem", state) is True
    assert chat.handle_interactive_line("/mcp resources filesystem", state) is True
    assert chat.handle_interactive_line("/mcp resource filesystem fake://readme", state) is True
    assert chat.handle_interactive_line("/mcp prompts filesystem", state) is True
    assert (
        chat.handle_interactive_line('/mcp prompt filesystem review {"topic":"quota"}', state)
        is True
    )
    assert (
        chat.handle_interactive_line('/mcp call filesystem read_file {"path":"README.md"}', state)
        is True
    )

    assert calls == [
        ("list", {"output_json": False}),
        ("tools", {"server_id": "filesystem", "timeout_seconds": 30.0, "output_json": False}),
        ("resources", {"server_id": "filesystem", "timeout_seconds": 30.0, "output_json": False}),
        (
            "resource",
            {
                "server_id": "filesystem",
                "uri": "fake://readme",
                "timeout_seconds": 30.0,
                "output_json": False,
            },
        ),
        ("prompts", {"server_id": "filesystem", "timeout_seconds": 30.0, "output_json": False}),
        (
            "prompt",
            {
                "server_id": "filesystem",
                "prompt_name": "review",
                "arguments_json": '{"topic":"quota"}',
                "timeout_seconds": 30.0,
                "output_json": False,
            },
        ),
        (
            "call",
            {
                "server_id": "filesystem",
                "tool_name": "read_file",
                "arguments_json": '{"path":"README.md"}',
                "workspace": tmp_path,
                "permission_mode": "suggest",
                "timeout_seconds": 30.0,
                "output_json": False,
            },
        ),
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
