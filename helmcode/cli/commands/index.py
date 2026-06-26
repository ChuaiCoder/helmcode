from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from helmcode.context.file_index import FileIndex
from helmcode.context.workspace import Workspace

console = Console()
app = typer.Typer(help="Build and inspect the local workspace file index.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def index_callback(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    limit: int = typer.Option(500, "--limit", "-n", min=1),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show index status when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        status_index(workspace=workspace, limit=limit, output_json=output_json)


@app.command("build")
def build_index(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    limit: int = typer.Option(500, "--limit", "-n", min=1),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Build or refresh the local file index cache."""
    ws = Workspace.discover(workspace)
    file_index = FileIndex(ws.root_path, ws.ignored_patterns)
    changed = file_index.update_cache()
    files = file_index.list_files(limit=limit, use_cache=False)
    payload = _status_payload(file_index, ws, files, changed)
    if output_json:
        _print_json(payload)
        return
    _print_status(payload)


@app.command("status")
def status_index(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    limit: int = typer.Option(500, "--limit", "-n", min=1),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show current file index status without refreshing the cache."""
    ws = Workspace.discover(workspace)
    file_index = FileIndex(ws.root_path, ws.ignored_patterns)
    files = file_index.list_files(limit=limit, use_cache=False)
    changed = file_index.get_changed_files()
    payload = _status_payload(file_index, ws, files, changed)
    if output_json:
        _print_json(payload)
        return
    _print_status(payload)


@app.command("changed")
def changed_index(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List files changed since the last index build."""
    ws = Workspace.discover(workspace)
    file_index = FileIndex(ws.root_path, ws.ignored_patterns)
    changed = file_index.get_changed_files()
    if output_json:
        _print_json(changed)
        return
    table = Table(title="Changed files")
    table.add_column("Path")
    for path in changed:
        table.add_row(path)
    console.print(table)


def _status_payload(
    file_index: FileIndex,
    workspace: Workspace,
    files: list[str],
    changed: list[str],
) -> dict[str, Any]:
    return {
        "workspace": str(workspace.root_path),
        "cache_path": str(file_index.cache_path),
        "cached_file_count": file_index.cached_file_count,
        "current_file_count": len(files),
        "changed_file_count": len(changed),
        "changed_files": changed,
        "languages": workspace.detected_languages,
        "frameworks": workspace.detected_frameworks,
        "test_commands": workspace.test_commands,
    }


def _print_status(payload: dict[str, Any]) -> None:
    table = Table(title="File index")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Workspace", str(payload["workspace"]))
    table.add_row("Cache", str(payload["cache_path"]))
    table.add_row("Cached files", str(payload["cached_file_count"]))
    table.add_row("Current files", str(payload["current_file_count"]))
    table.add_row("Changed files", str(payload["changed_file_count"]))
    table.add_row("Languages", ", ".join(payload["languages"]) or "unknown")
    table.add_row("Frameworks", ", ".join(payload["frameworks"]) or "unknown")
    table.add_row("Tests", ", ".join(payload["test_commands"]) or "not detected")
    console.print(table)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
