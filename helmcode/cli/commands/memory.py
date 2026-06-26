from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helmcode.memory.pinned_memory import MemoryEntry, PinnedMemoryStore

console = Console()
app = typer.Typer(help="Manage pinned project memory injected into task context.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def memory_main(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List pinned memory when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        list_memory(workspace=workspace, output_json=output_json)


@app.command("list")
def list_memory(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List pinned project memory."""
    entries = PinnedMemoryStore(workspace.resolve()).list()
    if output_json:
        _print_json([entry.to_dict() for entry in entries])
        return
    _print_memory_table(entries)


@app.command("add")
def add_memory(
    text: str = typer.Argument(..., help="Memory text to pin into future task context."),
    memory_id: str | None = typer.Option(None, "--id", help="Stable memory id."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Add pinned project memory."""
    try:
        entry = PinnedMemoryStore(workspace.resolve()).add(text, entry_id=memory_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output_json:
        _print_json(entry.to_dict())
        return
    console.print(f"Added memory: {entry.id}")


@app.command("show")
def show_memory(
    memory_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show one pinned memory entry."""
    try:
        entry = PinnedMemoryStore(workspace.resolve()).get(memory_id)
    except KeyError as exc:
        raise typer.BadParameter(f"unknown memory id: {memory_id}") from exc
    if output_json:
        _print_json(entry.to_dict())
        return
    console.print(Panel(entry.text, title=entry.id))
    console.print(f"Created: {entry.created_at}")


@app.command("forget")
def forget_memory(
    memory_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Delete one pinned memory entry."""
    if not yes and not typer.confirm(f"Forget memory {memory_id}?"):
        console.print("Memory unchanged.")
        return
    deleted = PinnedMemoryStore(workspace.resolve()).delete(memory_id)
    payload = {"memory_id": memory_id, "deleted": deleted}
    if output_json:
        _print_json(payload)
        return
    console.print("Forgot memory." if deleted else "Memory not found.")


@app.command("clear")
def clear_memory(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Clear all pinned project memory."""
    if not yes and not typer.confirm("Clear all pinned project memory?"):
        console.print("Memory unchanged.")
        return
    removed = PinnedMemoryStore(workspace.resolve()).clear()
    payload = {"removed": removed}
    if output_json:
        _print_json(payload)
        return
    console.print(f"Removed {removed} memory entr{'y' if removed == 1 else 'ies'}.")


def _print_memory_table(entries: list[MemoryEntry]) -> None:
    table = Table(title="Pinned project memory")
    table.add_column("ID")
    table.add_column("Created")
    table.add_column("Text")
    for entry in entries:
        table.add_row(entry.id, entry.created_at, _clip(entry.text, 80))
    if not entries:
        table.add_row("none", "", "")
    console.print(table)


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
