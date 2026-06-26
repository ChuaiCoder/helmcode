from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from helmcode.memory.checkpoint_store import (
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    Checkpoint,
    CheckpointStore,
    RestoreResult,
)

console = Console()
app = typer.Typer(help="Create and restore local workspace checkpoints.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def checkpoint_callback(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List checkpoints when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        list_checkpoints(workspace=workspace, output_json=output_json)


@app.command("create")
def create_checkpoint(
    label: str = typer.Argument("", help="Human-readable checkpoint label."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    max_files: int = typer.Option(DEFAULT_MAX_FILES, "--max-files", min=1),
    max_file_bytes: int = typer.Option(DEFAULT_MAX_FILE_BYTES, "--max-file-bytes", min=1),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Create a checkpoint of current non-sensitive workspace files."""
    checkpoint = CheckpointStore(workspace).create(
        label=label,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
    )
    if output_json:
        _print_json(checkpoint.metadata())
        return
    _print_checkpoint_summary(checkpoint)


@app.command("list")
def list_checkpoints(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List local checkpoints."""
    checkpoints = CheckpointStore(workspace).list()
    if output_json:
        _print_json([checkpoint.metadata() for checkpoint in checkpoints])
        return
    table = Table(title="Checkpoints")
    table.add_column("ID")
    table.add_column("Created")
    table.add_column("Files", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("Label")
    for checkpoint in checkpoints:
        table.add_row(
            checkpoint.id,
            checkpoint.created_at,
            str(checkpoint.file_count),
            str(checkpoint.total_bytes),
            checkpoint.label,
        )
    console.print(table)


@app.command("show")
def show_checkpoint(
    checkpoint_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show checkpoint metadata and captured file paths."""
    checkpoint = CheckpointStore(workspace).load(checkpoint_id)
    payload = {
        **checkpoint.metadata(),
        "files": sorted(checkpoint.files),
    }
    if output_json:
        _print_json(payload)
        return
    _print_checkpoint_summary(checkpoint)
    files = Table(title="Captured files")
    files.add_column("Path")
    for path in sorted(checkpoint.files):
        files.add_row(path)
    console.print(files)


@app.command("restore")
def restore_checkpoint(
    checkpoint_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    path: list[str] | None = typer.Option(None, "--path", "-p", help="Restore only this relative path."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be restored."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Restore files from a checkpoint."""
    if not dry_run and not yes:
        if not typer.confirm(f"Restore files from checkpoint {checkpoint_id}?"):
            console.print("Restore cancelled.")
            return
    result = CheckpointStore(workspace).restore(
        checkpoint_id,
        paths=path,
        dry_run=dry_run,
    )
    if output_json:
        _print_json(result.to_dict())
        return
    _print_restore_result(result)


@app.command("delete")
def delete_checkpoint(
    checkpoint_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Delete a checkpoint file."""
    if not yes and not typer.confirm(f"Delete checkpoint {checkpoint_id}?"):
        console.print("Delete cancelled.")
        return
    deleted = CheckpointStore(workspace).delete(checkpoint_id)
    payload = {"checkpoint_id": checkpoint_id, "deleted": deleted}
    if output_json:
        _print_json(payload)
        return
    console.print("Deleted." if deleted else "Checkpoint not found.")


def _print_checkpoint_summary(checkpoint: Checkpoint) -> None:
    table = Table(title="Checkpoint")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("ID", checkpoint.id)
    table.add_row("Label", checkpoint.label)
    table.add_row("Created", checkpoint.created_at)
    table.add_row("Files", str(checkpoint.file_count))
    table.add_row("Bytes", str(checkpoint.total_bytes))
    table.add_row("Git branch", checkpoint.git_branch or "unknown")
    table.add_row("Git head", checkpoint.git_head or "unknown")
    table.add_row("Skipped", str(len(checkpoint.skipped)))
    console.print(table)


def _print_restore_result(result: RestoreResult) -> None:
    table = Table(title="Checkpoint restore")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Checkpoint", result.checkpoint_id)
    table.add_row("Dry run", "yes" if result.dry_run else "no")
    table.add_row("Restored files", str(len(result.restored_files)))
    table.add_row("Missing files", str(len(result.missing_files)))
    console.print(table)
    if result.restored_files:
        restored = Table(title="Files")
        restored.add_column("Path")
        for file_path in result.restored_files:
            restored.add_row(file_path)
        console.print(restored)
    if result.missing_files:
        missing = Table(title="Missing from checkpoint")
        missing.add_column("Path")
        for file_path in result.missing_files:
            missing.add_row(file_path)
        console.print(missing)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
