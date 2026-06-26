from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helmcode.memory.session_compaction import SessionCompaction, SessionCompactionStore
from helmcode.memory.session_store import SessionStore

console = Console()


def compact_cmd(
    session_id: str | None = typer.Argument(None, help="Session id to compact. Defaults to latest session."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    list_compactions: bool = typer.Option(False, "--list", help="List existing compactions."),
    show_text: bool = typer.Option(False, "--show-text", help="Print compacted markdown text."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Compact a session timeline into a reusable local markdown archive."""
    workspace = workspace.resolve()
    compactions = SessionCompactionStore(workspace)
    if list_compactions:
        items = compactions.list()
        if output_json:
            print(json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2))
            return
        _print_compactions(items)
        return

    target_session_id = session_id or _latest_session_id(workspace)
    if target_session_id is None:
        console.print("[yellow]No sessions found to compact.[/yellow]")
        raise typer.Exit(1)
    try:
        compaction = compactions.compact(target_session_id)
    except ValueError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(1) from exc

    if output_json:
        payload: dict[str, Any] = compaction.to_dict()
        if show_text:
            payload["text"] = compactions.read_text(compaction.session_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_compaction(compaction)
    if show_text:
        console.print(Panel(compactions.read_text(compaction.session_id), title="Compaction"))


def _latest_session_id(workspace: Path) -> str | None:
    sessions = SessionStore(workspace).list_sessions(limit=1)
    if not sessions:
        return None
    return sessions[0].session_id


def _print_compaction(compaction: SessionCompaction) -> None:
    table = Table(title="Session compaction")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Session", compaction.session_id)
    table.add_row("Path", str(compaction.path))
    table.add_row("Events", str(compaction.event_count))
    table.add_row("Source chars", str(compaction.source_chars))
    table.add_row("Compacted chars", str(compaction.compacted_chars))
    table.add_row("Task", compaction.task or "unknown")
    console.print(table)


def _print_compactions(compactions: list[SessionCompaction]) -> None:
    table = Table(title="Session compactions")
    table.add_column("Session")
    table.add_column("Created")
    table.add_column("Events", justify="right")
    table.add_column("Chars")
    table.add_column("Path")
    for item in compactions:
        table.add_row(
            item.session_id,
            item.created_at.isoformat(timespec="seconds"),
            str(item.event_count),
            f"{item.source_chars} -> {item.compacted_chars}",
            str(item.path),
        )
    console.print(table)
