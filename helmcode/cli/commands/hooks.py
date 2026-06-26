from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.memory.hooks import HOOK_EVENT_DESCRIPTIONS, HOOK_EVENTS, Hook, HookStore

console = Console()
app = typer.Typer(help="Manage workspace lifecycle hooks.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def hooks_main(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    event: str | None = typer.Option(None, "--event", help="Filter by hook event."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List hooks when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        list_hooks(workspace=workspace, event=event, output_json=output_json)


@app.command("list")
def list_hooks(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    event: str | None = typer.Option(None, "--event", help="Filter by hook event."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List configured lifecycle hooks."""
    store = HookStore(workspace.resolve())
    try:
        hooks = store.list()
        if event:
            _validate_cli_event(event)
            hooks = [hook for hook in hooks if hook.event == event]
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output_json:
        _print_json([hook.to_dict() for hook in hooks])
        return
    _print_hooks_table(hooks)


@app.command("events")
def list_events(
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List supported hook events."""
    payload = [
        {"event": event, "description": HOOK_EVENT_DESCRIPTIONS[event]}
        for event in HOOK_EVENTS
    ]
    if output_json:
        _print_json(payload)
        return
    table = Table(title="Hook events")
    table.add_column("Event")
    table.add_column("When")
    for item in payload:
        table.add_row(str(item["event"]), str(item["description"]))
    console.print(table)


@app.command("add")
def add_hook(
    event: str = typer.Argument(..., help="Hook event, for example: pre_plan."),
    command: str = typer.Argument(..., help="Shell command to run. Quote commands with spaces."),
    hook_id: str | None = typer.Option(None, "--id", help="Stable hook id."),
    required: bool = typer.Option(
        False,
        "--required",
        help="Block the agent workflow if this hook fails.",
    ),
    disabled: bool = typer.Option(False, "--disabled", help="Store the hook disabled."),
    timeout_seconds: int = typer.Option(
        30,
        "--timeout",
        min=1,
        max=600,
        help="Hook command timeout in seconds.",
    ),
    description: str = typer.Option("", "--description", help="Short human-readable note."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Add a lifecycle hook."""
    try:
        hook = HookStore(workspace.resolve()).add(
            event=event,
            command=command,
            hook_id=hook_id,
            required=required,
            enabled=not disabled,
            timeout_seconds=timeout_seconds,
            description=description,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output_json:
        _print_json(hook.to_dict())
        return
    console.print(f"Added hook: {hook.id}")


@app.command("show")
def show_hook(
    hook_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show one hook."""
    try:
        hook = HookStore(workspace.resolve()).get(hook_id)
    except KeyError as exc:
        raise typer.BadParameter(f"unknown hook id: {hook_id}") from exc
    if output_json:
        _print_json(hook.to_dict())
        return
    _print_hooks_table([hook])


@app.command("remove")
def remove_hook(
    hook_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Remove one hook."""
    if not yes and not typer.confirm(f"Remove hook {hook_id}?"):
        console.print("Hooks unchanged.")
        return
    removed = HookStore(workspace.resolve()).remove(hook_id)
    payload = {"hook_id": hook_id, "removed": removed}
    if output_json:
        _print_json(payload)
        return
    console.print("Removed hook." if removed else "Hook not found.")


@app.command("enable")
def enable_hook(
    hook_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Enable one hook."""
    changed = HookStore(workspace.resolve()).set_enabled(hook_id, True)
    payload = {"hook_id": hook_id, "enabled": True, "changed": changed}
    if output_json:
        _print_json(payload)
        return
    console.print("Enabled hook." if changed else "Hook not found.")


@app.command("disable")
def disable_hook(
    hook_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Disable one hook."""
    changed = HookStore(workspace.resolve()).set_enabled(hook_id, False)
    payload = {"hook_id": hook_id, "enabled": False, "changed": changed}
    if output_json:
        _print_json(payload)
        return
    console.print("Disabled hook." if changed else "Hook not found.")


@app.command("require")
def require_hook(
    hook_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Mark one hook as required."""
    changed = HookStore(workspace.resolve()).set_required(hook_id, True)
    payload = {"hook_id": hook_id, "required": True, "changed": changed}
    if output_json:
        _print_json(payload)
        return
    console.print("Hook is now required." if changed else "Hook not found.")


@app.command("optional")
def optional_hook(
    hook_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Mark one hook as non-blocking."""
    changed = HookStore(workspace.resolve()).set_required(hook_id, False)
    payload = {"hook_id": hook_id, "required": False, "changed": changed}
    if output_json:
        _print_json(payload)
        return
    console.print("Hook is now optional." if changed else "Hook not found.")


@app.command("clear")
def clear_hooks(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Clear all configured hooks."""
    if not yes and not typer.confirm("Clear all workspace hooks?"):
        console.print("Hooks unchanged.")
        return
    removed = HookStore(workspace.resolve()).clear()
    payload = {"removed": removed}
    if output_json:
        _print_json(payload)
        return
    console.print(f"Removed {removed} hook(s).")


def _print_hooks_table(hooks: list[Hook]) -> None:
    table = Table(title="Workspace hooks")
    table.add_column("ID")
    table.add_column("Event")
    table.add_column("State")
    table.add_column("Required")
    table.add_column("Timeout")
    table.add_column("Command")
    for hook in hooks:
        table.add_row(
            hook.id,
            hook.event,
            "enabled" if hook.enabled else "disabled",
            "yes" if hook.required else "no",
            f"{hook.timeout_seconds}s",
            hook.command,
        )
    if not hooks:
        table.add_row("none", "", "", "", "", "")
    console.print(table)


def _validate_cli_event(event: str) -> None:
    if event not in HOOK_EVENTS:
        raise ValueError(f"hook event must be one of: {', '.join(HOOK_EVENTS)}")


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
