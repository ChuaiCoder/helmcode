from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.safety.command_policy import CommandPolicy, CommandRisk
from helmcode.safety.permission_store import PermissionStore

console = Console()
app = typer.Typer(help="Manage workspace shell command permissions.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def permissions_main(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List workspace permissions when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        list_permissions(workspace=workspace, output_json=output_json)


@app.command("list")
def list_permissions(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List allowed shell command prefixes."""
    store = PermissionStore.for_workspace(workspace.resolve())
    payload = store.to_dict()
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_permissions(store)


@app.command("add")
def add_permission(
    command_prefix: str = typer.Argument(..., help="Allowed shell command prefix, for example: git push"),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Add an allowed shell command prefix for this workspace."""
    prefix = " ".join(command_prefix.strip().split())
    if not prefix:
        raise typer.BadParameter("command prefix cannot be empty")
    _validate_safe_to_store(prefix)
    if not yes and not typer.confirm(f"Allow shell commands starting with {prefix!r} in this workspace?"):
        console.print("Permission unchanged.")
        return
    store = PermissionStore.for_workspace(workspace.resolve())
    added = store.add(prefix)
    payload = {**store.to_dict(), "added": added, "command_prefix": prefix}
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    console.print(f"{'Added' if added else 'Already allowed'}: {prefix}")


@app.command("remove")
def remove_permission(
    command_prefix: str = typer.Argument(..., help="Allowed shell command prefix to remove."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Remove an allowed shell command prefix."""
    prefix = " ".join(command_prefix.strip().split())
    if not yes and not typer.confirm(f"Remove permission for {prefix!r}?"):
        console.print("Permission unchanged.")
        return
    store = PermissionStore.for_workspace(workspace.resolve())
    removed = store.remove(prefix)
    payload = {**store.to_dict(), "removed": removed, "command_prefix": prefix}
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    console.print(f"{'Removed' if removed else 'Not found'}: {prefix}")


@app.command("clear")
def clear_permissions(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Clear all allowed shell command prefixes."""
    if not yes and not typer.confirm("Clear all workspace shell command permissions?"):
        console.print("Permissions unchanged.")
        return
    store = PermissionStore.for_workspace(workspace.resolve())
    removed = store.clear()
    payload = {**store.to_dict(), "removed": removed}
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    console.print(f"Removed {removed} permission(s).")


def _validate_safe_to_store(command_prefix: str) -> None:
    result = CommandPolicy(use_ast_analysis=False).check(
        command_prefix,
        permission_mode="auto",
        allowed_prefixes=[command_prefix],
    )
    if result.risk == CommandRisk.BLOCKED:
        raise typer.BadParameter(f"refusing to store blocked command prefix: {result.reason}")


def _print_permissions(store: PermissionStore) -> None:
    table = Table(title="Workspace permissions")
    table.add_column("Allowed command prefix")
    for command in store.allowed_commands:
        table.add_row(command)
    if not store.allowed_commands:
        table.add_row("none")
    console.print(table)
