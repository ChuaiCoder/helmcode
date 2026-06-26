from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from helmcode.memory.session_store import SessionEvent, SessionStats, SessionStore, SessionSummary

console = Console()
app = typer.Typer(help="Inspect local agent sessions and audit events.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def sessions_callback(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    limit: int = typer.Option(20, "--limit", "-n", min=1),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List recent sessions when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        list_sessions_command(workspace=workspace, limit=limit, output_json=output_json)


@app.command("list")
def list_sessions_command(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    limit: int = typer.Option(20, "--limit", "-n", min=1),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List recent local agent sessions."""
    store = SessionStore(workspace.resolve())
    summaries = store.list_sessions(limit=limit)
    if output_json:
        _print_json([summary.to_dict() for summary in summaries])
        return
    _print_session_table(summaries)


@app.command("events")
def events_command(
    session_id: str | None = typer.Argument(None),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    limit: int = typer.Option(50, "--limit", "-n", min=1),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show recent events, optionally filtered by session id."""
    store = SessionStore(workspace.resolve())
    events = store.list_recent_events(session_id=session_id, limit=limit)
    if output_json:
        _print_json([event.to_dict() for event in events])
        return
    _print_events_table(events)


@app.command("stats")
def stats_command(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show aggregate local session statistics."""
    store = SessionStore(workspace.resolve())
    stats = store.stats()
    if output_json:
        _print_json(stats.to_dict())
        return
    _print_stats(stats)


def _print_session_table(summaries: list[SessionSummary]) -> None:
    table = Table(title="Agent sessions")
    table.add_column("Session")
    table.add_column("Started")
    table.add_column("Updated")
    table.add_column("Events", justify="right")
    table.add_column("Task")
    for summary in summaries:
        table.add_row(
            summary.session_id,
            summary.started_at.isoformat(timespec="seconds"),
            summary.updated_at.isoformat(timespec="seconds"),
            str(summary.event_count),
            _clip(summary.task or "", 80),
        )
    console.print(table)


def _print_events_table(events: list[SessionEvent]) -> None:
    table = Table(title="Session events")
    table.add_column("Time")
    table.add_column("Session")
    table.add_column("Type")
    table.add_column("Payload")
    for event in events:
        table.add_row(
            event.created_at.isoformat(timespec="seconds"),
            event.session_id,
            event.event_type,
            _clip(json.dumps(event.payload, ensure_ascii=False, default=str), 100),
        )
    console.print(table)


def _print_stats(stats: SessionStats) -> None:
    summary = Table(title="Session stats")
    summary.add_column("Metric")
    summary.add_column("Value")
    summary.add_row("Sessions", str(stats.session_count))
    summary.add_row("Events", str(stats.event_count))
    summary.add_row("Model calls", str(stats.model_call_count))
    summary.add_row("Patches created", str(stats.patch_created_count))
    summary.add_row("Patches applied", str(stats.patch_applied_count))
    summary.add_row("Command results", str(stats.command_result_count))
    summary.add_row("First event", stats.first_event_at.isoformat() if stats.first_event_at else "none")
    summary.add_row("Last event", stats.last_event_at.isoformat() if stats.last_event_at else "none")
    console.print(summary)

    if stats.event_counts:
        events = Table(title="Events by type")
        events.add_column("Type")
        events.add_column("Count", justify="right")
        for event_type, count in sorted(stats.event_counts.items()):
            events.add_row(event_type, str(count))
        console.print(events)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
