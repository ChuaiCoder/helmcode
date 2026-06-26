from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helmcode.cli.commands import (
    agents,
    allocations,
    apply,
    checkpoints,
    config as config_command,
    compact,
    context,
    cost,
    diff,
    doctor,
    index,
    init_project,
    keys,
    mcp,
    models,
    plan,
    quota,
    retry,
    routes,
    run,
    savings,
    sessions,
    skills,
    tokens,
    tools,
)
from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config
from helmcode.models.quota import QuotaAwareSelector, QuotaLedger

console = Console()

ActionMode = str


@dataclass(slots=True)
class InteractiveState:
    workspace_path: Path
    action_mode: ActionMode = "recommend"
    routing_mode: str = "quota"
    forced_model: str | None = None
    max_cost_score: int | None = None
    preplan_cache: bool = True
    yes: bool = False
    run_tests: bool = True


def chat_cmd(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    mode: str = typer.Option("recommend", "--mode", help="Default bare prompt action: recommend, plan, or run."),
    routing: str | None = typer.Option(None, "--routing", help="Model routing: fixed, quota, or recommend."),
    model: str | None = typer.Option(None, "--model", help="Force all model calls to this provider:model id."),
    max_cost_score: int | None = typer.Option(
        None,
        "--max-cost-score",
        min=1,
        help="Block plan/run before provider calls if Coding Plan selected cost score exceeds this value.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve safe confirmations where allowed."),
    no_tests: bool = typer.Option(False, "--no-tests", help="Skip tests for /run."),
    no_preplan_cache: bool = typer.Option(
        False,
        "--no-preplan-cache",
        help="Disable cached scout/summarizer pre-plan findings for this session.",
    ),
) -> None:
    """Start an interactive helmcode session."""
    config = load_config()
    state = InteractiveState(
        workspace_path=workspace.resolve(),
        action_mode=_normalize_mode(mode),
        routing_mode=_normalize_routing(routing or config.routing_mode),
        forced_model=model,
        max_cost_score=max_cost_score,
        preplan_cache=not no_preplan_cache,
        yes=yes,
        run_tests=not no_tests,
    )
    start_interactive(state)


def start_interactive(workspace_or_state: Path | InteractiveState) -> None:
    """Start an interactive CLI session."""
    if isinstance(workspace_or_state, InteractiveState):
        state = workspace_or_state
    else:
        config = load_config()
        state = InteractiveState(
            workspace_path=workspace_or_state.resolve(),
            routing_mode=_normalize_routing(config.routing_mode),
        )
    _print_banner(state)
    _print_help(compact=True)
    while True:
        try:
            line = console.input(_prompt(state)).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if not line:
            continue
        try:
            if not handle_interactive_line(line, state):
                return
        except typer.Exit:
            continue
        except Exception as exc:
            console.print(Panel(f"[red]Error:[/red] {exc}", title="Command failed"))


def handle_interactive_line(line: str, state: InteractiveState) -> bool:
    command, rest = _split_line(line)
    if command in {"/exit", "/quit", "exit", "quit"}:
        return False
    if command == "/help":
        _print_help(compact=False)
        return True
    if command == "/new":
        _new_session_state(state)
        return True
    if command == "/clear":
        console.clear()
        _print_banner(state)
        return True
    if command == "/status":
        _print_status(state)
        return True
    if command == "/keys":
        keys.keys_cmd(config_path=None, output_json=False)
        return True
    if command == "/models":
        models.list_models()
        return True
    if command == "/quota":
        _quota(rest, state)
        return True
    if command == "/budget":
        _set_budget(state, rest)
        return True
    if command == "/cache":
        state.preplan_cache = _parse_on_off(rest, current=state.preplan_cache)
        console.print(f"Pre-plan cache: {'on' if state.preplan_cache else 'off'}")
        return True
    if command == "/index":
        index.status_index(workspace=state.workspace_path)
        return True
    if command == "/changed":
        index.changed_index(workspace=state.workspace_path)
        return True
    if command == "/sessions":
        sessions.list_sessions_command(workspace=state.workspace_path)
        return True
    if command == "/events":
        sessions.events_command(session_id=rest or None, workspace=state.workspace_path)
        return True
    if command == "/replay":
        _require_task(rest, "/replay")
        sessions.replay_command(session_id=rest, workspace=state.workspace_path)
        return True
    if command == "/retry":
        retry.retry_cmd(
            session_id=rest or None,
            workspace=state.workspace_path,
            mode=state.action_mode,
            routing=state.routing_mode,
            model=state.forced_model,
            max_cost_score=state.max_cost_score,
            yes=state.yes,
            no_tests=not state.run_tests,
            no_preplan_cache=not state.preplan_cache,
        )
        return True
    if command == "/session-diff":
        parts = rest.split()
        if len(parts) != 2:
            raise ValueError("/session-diff requires two session ids")
        sessions.diff_command(
            left_session_id=parts[0],
            right_session_id=parts[1],
            workspace=state.workspace_path,
        )
        return True
    if command == "/prune-sessions":
        sessions.prune_command(workspace=state.workspace_path)
        return True
    if command == "/compact":
        compact.compact_cmd(
            session_id=rest or None,
            workspace=state.workspace_path,
            list_compactions=False,
            show_text=False,
            output_json=False,
        )
        return True
    if command == "/stats":
        sessions.stats_command(workspace=state.workspace_path)
        return True
    if command == "/tokens":
        tokens.tokens_cmd(
            workspace=state.workspace_path,
            session_id=rest or None,
            limit=None,
            output_json=False,
        )
        return True
    if command == "/agents":
        if rest:
            _agents(rest, state)
        else:
            agents.list_agents()
        return True
    if command == "/context":
        _require_task(rest, "/context")
        context.context_cmd(
            task=rest,
            workspace=state.workspace_path,
            show_text=False,
            output_json=False,
            max_file_chars=4_000,
            max_explicit_files=8,
        )
        return True
    if command == "/cost":
        _require_task(rest, "/cost")
        cost.cost_cmd(
            task=rest,
            workspace=state.workspace_path,
            routing="quota" if state.routing_mode == "recommend" else state.routing_mode,
            model=state.forced_model,
            include_repair=False,
            max_cost_score=state.max_cost_score,
            max_file_chars=4_000,
            max_explicit_files=8,
            output_json=False,
        )
        return True
    if command == "/routes":
        _require_task(rest, "/routes")
        routes.routes_cmd(
            task=rest,
            workspace=state.workspace_path,
            model=state.forced_model,
            include_repair=False,
            max_cost_score=state.max_cost_score,
            output_json=False,
        )
        return True
    if command == "/savings":
        savings.savings_cmd(
            workspace=state.workspace_path,
            limit=None,
            output_json=False,
        )
        return True
    if command in {"/allocations", "/plans"}:
        allocations.allocations_cmd(
            workspace=state.workspace_path,
            session_id=rest or None,
            limit=20,
            output_json=False,
        )
        return True
    if command == "/skills":
        skills.list_skills(workspace=state.workspace_path)
        return True
    if command == "/skill-match":
        _require_task(rest, "/skill-match")
        skills.match_skills(task=rest, workspace=state.workspace_path)
        return True
    if command == "/tools":
        tools.list_tools()
        return True
    if command == "/mcp":
        mcp.list_mcp()
        return True
    if command == "/tool":
        parts = rest.split(maxsplit=1)
        if not parts:
            raise ValueError("/tool requires a tool name")
        tools.run_tool(
            tool_name=parts[0],
            input_json=parts[1] if len(parts) == 2 else "{}",
            workspace=state.workspace_path,
        )
        return True
    if command == "/checkpoint":
        checkpoints.create_checkpoint(label=rest, workspace=state.workspace_path)
        return True
    if command == "/checkpoints":
        checkpoints.list_checkpoints(workspace=state.workspace_path)
        return True
    if command == "/restore":
        _require_task(rest, "/restore")
        checkpoints.restore_checkpoint(checkpoint_id=rest, workspace=state.workspace_path, yes=state.yes)
        return True
    if command == "/doctor":
        doctor.doctor(workspace=state.workspace_path)
        return True
    if command == "/config":
        config_command.config_cmd(show=True, init=False)
        return True
    if command == "/init":
        init_project.init_cmd(workspace=state.workspace_path)
        return True
    if command == "/setup":
        console.print("Run `helmcode setup` outside the interactive session to configure providers and quotas.")
        return True
    if command == "/diff":
        diff.show_pending_diff(workspace=state.workspace_path)
        return True
    if command == "/apply":
        apply.apply_last_patch(workspace=state.workspace_path, yes=state.yes)
        return True
    if command == "/mode":
        _set_mode(state, rest)
        return True
    if command == "/routing":
        _set_routing(state, rest)
        return True
    if command == "/model":
        _set_model(state, rest)
        return True
    if command == "/yes":
        state.yes = _parse_on_off(rest, current=state.yes)
        console.print(f"Auto-confirm: {'on' if state.yes else 'off'}")
        return True
    if command == "/tests":
        state.run_tests = _parse_on_off(rest, current=state.run_tests)
        console.print(f"Run tests: {'on' if state.run_tests else 'off'}")
        return True
    if command == "/recommend":
        _require_task(rest, "/recommend")
        _recommend(rest, state)
        return True
    if command == "/plan":
        _require_task(rest, "/plan")
        _plan(rest, state)
        return True
    if command == "/run":
        _require_task(rest, "/run")
        _run(rest, state)
        return True
    if command.startswith("/"):
        console.print(f"[yellow]Unknown command:[/yellow] {command}. Type /help.")
        return True

    if state.action_mode == "recommend":
        _recommend(line, state)
    elif state.action_mode == "plan":
        _plan(line, state)
    elif state.action_mode == "run":
        _run(line, state)
    else:
        raise ValueError(f"unknown mode: {state.action_mode}")
    return True


def _recommend(task: str, state: InteractiveState) -> None:
    run.run_task(
        task=task,
        workspace=state.workspace_path,
        yes=state.yes,
        no_tests=not state.run_tests,
        routing="recommend",
        model=state.forced_model,
        max_cost_score=state.max_cost_score,
        no_preplan_cache=not state.preplan_cache,
    )


def _agents(task: str, state: InteractiveState) -> None:
    allocation = agents.build_allocation(
        task=task,
        workspace=state.workspace_path,
        routing="quota" if state.routing_mode == "recommend" else state.routing_mode,
        model=state.forced_model,
        include_repair=False,
        max_cost_score=state.max_cost_score,
    )
    agents.print_allocation(allocation)


def _plan(task: str, state: InteractiveState) -> None:
    routing = "quota" if state.routing_mode == "recommend" else state.routing_mode
    plan.plan_task(
        task=task,
        workspace=state.workspace_path,
        routing=routing,
        model=state.forced_model,
        max_cost_score=state.max_cost_score,
        no_preplan_cache=not state.preplan_cache,
    )


def _run(task: str, state: InteractiveState) -> None:
    run.run_task(
        task=task,
        workspace=state.workspace_path,
        yes=state.yes,
        no_tests=not state.run_tests,
        routing=state.routing_mode,
        model=state.forced_model,
        max_cost_score=state.max_cost_score,
        no_preplan_cache=not state.preplan_cache,
    )


def _print_banner(state: InteractiveState) -> None:
    workspace = Workspace.discover(state.workspace_path)
    config = load_config()
    table = Table(title="helmcode")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Project", str(workspace.root_path))
    table.add_row("Git branch", workspace.current_branch or "not a git repo")
    table.add_row("Languages", ", ".join(workspace.detected_languages) or "unknown")
    table.add_row("Tests", ", ".join(workspace.test_commands) or "not detected")
    table.add_row("Permission", config.permission_mode)
    table.add_row("Mode", state.action_mode)
    table.add_row("Routing", state.routing_mode)
    table.add_row("Forced model", state.forced_model or "none")
    table.add_row("Budget", str(state.max_cost_score) if state.max_cost_score is not None else "none")
    table.add_row("Pre-plan cache", "on" if state.preplan_cache else "off")
    console.print(table)


def _print_status(state: InteractiveState) -> None:
    _print_banner(state)
    config = load_config()
    selector = QuotaAwareSelector(config, QuotaLedger.for_workspace(state.workspace_path))
    quota_table = Table(title="Local quota")
    quota_table.add_column("Model")
    quota_table.add_column("Policy")
    quota_table.add_column("Windows")
    for status in selector.status_for_configured_models():
        windows = quota._quota_windows_text(status)
        quota_table.add_row(status.model_id, status.policy_id or "unmetered", windows or "no local policy")
    console.print(quota_table)


def _print_help(compact: bool) -> None:
    commands = [
        ("/recommend <task>", "Show Coding Plan allocation without calling a provider."),
        ("/plan <task>", "Generate a plan through the selected planning model."),
        ("/run <task>", "Run plan, patch, review, apply confirmation, and tests."),
        ("/retry [session]", "Retry the latest task using the current mode and routing."),
        ("/new", "Reset the current interactive state."),
        ("/clear", "Clear the screen and redraw the session status."),
        ("/mode recommend|plan|run", "Set what bare prompt text does."),
        ("/routing fixed|quota|recommend", "Set model routing for this session."),
        ("/model <id|clear>", "Force a provider:model id or clear the override."),
        ("/budget <score|clear>", "Set a Coding Plan max cost score for plan/run."),
        ("/cache on|off", "Toggle cached scout/summarizer pre-plan findings."),
        ("/agents <task>", "Show quota-saving multi-agent assignment."),
        ("/context <task>", "Preview model context without calling a provider."),
        ("/cost <task>", "Preview context, allocation, and quota cost."),
        ("/routes <task>", "Compare fixed/quota/forced Coding Plan routes."),
        ("/savings", "Show historical Coding Plan savings."),
        ("/allocations [session]", "Show Coding Plan allocation history."),
        ("/skills", "List built-in and project skills."),
        ("/skill-match <task>", "Show skills matched for a task."),
        ("/tools", "List local tools."),
        ("/mcp", "List configured MCP servers."),
        ("/tool <name> <json>", "Run a local tool."),
        ("/checkpoint [label]", "Create a local workspace checkpoint."),
        ("/checkpoints", "List local checkpoints."),
        ("/restore <id>", "Restore a checkpoint after confirmation."),
        ("/models", "Show configured roles and model profiles."),
        ("/keys", "Show provider key readiness without printing secrets."),
        ("/quota [history|reset]", "Show or manage local quota estimates."),
        ("/index", "Show local file index status."),
        ("/changed", "Show files changed since index build."),
        ("/sessions", "Show recent local sessions."),
        ("/events [session]", "Show recent audit events."),
        ("/replay <session>", "Replay one session timeline."),
        ("/session-diff <a> <b>", "Compare two sessions."),
        ("/compact [session]", "Compact session history into local markdown."),
        ("/prune-sessions", "Delete old session records after confirmation."),
        ("/stats", "Show aggregate session stats."),
        ("/tokens [session]", "Show model token and cache usage."),
        ("/status", "Show workspace, mode, routing, and quota."),
        ("/diff", "Show pending patch."),
        ("/apply", "Apply pending patch."),
        ("/doctor", "Run local diagnostics."),
        ("/init", "Create AGENTS.md project instructions."),
        ("/setup", "Show setup command hint."),
        ("/yes on|off", "Toggle auto-confirm for safe confirmations."),
        ("/tests on|off", "Toggle tests for /run."),
        ("/exit", "Leave the session."),
    ]
    table = Table(title="Commands")
    table.add_column("Command")
    table.add_column("Description")
    for command, description in commands if not compact else commands[:7]:
        table.add_row(command, description)
    console.print(table)
    if compact:
        console.print("Type /help for all commands. Bare text uses the current /mode.")


def _prompt(state: InteractiveState) -> str:
    model = f" model={state.forced_model}" if state.forced_model else ""
    return f"[bold]helmcode:{state.action_mode}:{state.routing_mode}{model}> [/bold]"


def _split_line(line: str) -> tuple[str, str]:
    parts = line.split(maxsplit=1)
    command = parts[0]
    rest = parts[1].strip() if len(parts) == 2 else ""
    return command, rest


def _set_mode(state: InteractiveState, value: str) -> None:
    if not value:
        console.print(f"Current mode: {state.action_mode}")
        return
    state.action_mode = _normalize_mode(value)
    console.print(f"Mode: {state.action_mode}")


def _set_routing(state: InteractiveState, value: str) -> None:
    if not value:
        console.print(f"Current routing: {state.routing_mode}")
        return
    state.routing_mode = _normalize_routing(value)
    console.print(f"Routing: {state.routing_mode}")


def _set_model(state: InteractiveState, value: str) -> None:
    if not value:
        console.print(f"Forced model: {state.forced_model or 'none'}")
        return
    if value in {"clear", "none", "off"}:
        state.forced_model = None
    else:
        state.forced_model = value
    console.print(f"Forced model: {state.forced_model or 'none'}")


def _new_session_state(state: InteractiveState) -> None:
    config = load_config()
    state.action_mode = "recommend"
    state.routing_mode = _normalize_routing(config.routing_mode)
    state.forced_model = None
    state.max_cost_score = None
    state.preplan_cache = True
    state.yes = False
    state.run_tests = True
    console.print("New interactive state started.")


def _set_budget(state: InteractiveState, value: str) -> None:
    if not value:
        console.print(f"Budget: {state.max_cost_score if state.max_cost_score is not None else 'none'}")
        return
    if value in {"clear", "none", "off"}:
        state.max_cost_score = None
    else:
        try:
            budget = int(value)
        except ValueError as exc:
            raise ValueError("budget must be a positive integer or clear") from exc
        if budget <= 0:
            raise ValueError("budget must be a positive integer or clear")
        state.max_cost_score = budget
    console.print(f"Budget: {state.max_cost_score if state.max_cost_score is not None else 'none'}")


def _parse_on_off(value: str, current: bool) -> bool:
    if not value:
        return not current
    if value in {"on", "yes", "true", "1"}:
        return True
    if value in {"off", "no", "false", "0"}:
        return False
    raise ValueError("expected on or off")


def _require_task(task: str, command: str) -> None:
    if not task:
        raise ValueError(f"{command} requires a task")


def _quota(rest: str, state: InteractiveState) -> None:
    parts = rest.split()
    if not parts:
        quota.status_quota(workspace=state.workspace_path)
        return
    subcommand = parts[0]
    if subcommand == "history":
        quota.history_quota(
            workspace=state.workspace_path,
            model_id=None,
            unit=None,
            role=None,
            limit=20,
            output_json=False,
        )
        return
    if subcommand == "reset":
        if len(parts) > 1 and parts[1] in {"yes", "--yes", "-y"}:
            quota.reset_quota(
                workspace=state.workspace_path,
                model_id=None,
                unit=None,
                role=None,
                yes=True,
            )
            return
        console.print("Run `/quota reset yes` to clear the local quota ledger from the interactive session.")
        return
    raise ValueError("/quota supports: history, reset")


def _normalize_mode(value: str) -> str:
    if value not in {"recommend", "plan", "run"}:
        raise typer.BadParameter("mode must be one of: recommend, plan, run")
    return value


def _normalize_routing(value: str) -> str:
    if value not in {"fixed", "quota", "recommend"}:
        raise typer.BadParameter("routing must be one of: fixed, quota, recommend")
    return value
