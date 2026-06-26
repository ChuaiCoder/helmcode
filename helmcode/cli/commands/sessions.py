from __future__ import annotations

import json
from collections import Counter
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


@app.command("replay")
def replay_command(
    session_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Replay one session as an ordered event timeline."""
    store = SessionStore(workspace.resolve())
    events = store.list_events(session_id)
    if not events:
        console.print(f"[yellow]No events found for session:[/yellow] {session_id}")
        raise typer.Exit(1)
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


@app.command("diff")
def diff_command(
    left_session_id: str = typer.Argument(...),
    right_session_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Compare two local sessions."""
    store = SessionStore(workspace.resolve())
    diff = build_session_diff(store, left_session_id, right_session_id)
    if output_json:
        _print_json(diff)
        return
    _print_diff(diff)


@app.command("prune")
def prune_command(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    keep: int = typer.Option(20, "--keep", min=0, help="Keep this many newest sessions."),
    older_than_days: int | None = typer.Option(None, "--older-than-days", min=1),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Delete old local session events."""
    if not yes:
        detail = f"outside newest {keep} sessions"
        if older_than_days is not None:
            detail += f" and older than {older_than_days} day(s)"
        if not typer.confirm(f"Delete local session events {detail}?"):
            console.print("Prune cancelled.")
            return
    store = SessionStore(workspace.resolve())
    pruned = store.prune_sessions(keep=keep, older_than_days=older_than_days)
    payload = [summary.to_dict() for summary in pruned]
    if output_json:
        _print_json(payload)
        return
    if not pruned:
        console.print("No sessions pruned.")
        return
    console.print(f"Pruned {len(pruned)} session(s).")
    _print_session_table(pruned)


def build_session_diff(
    store: SessionStore,
    left_session_id: str,
    right_session_id: str,
) -> dict[str, Any]:
    left = _session_digest(store, left_session_id)
    right = _session_digest(store, right_session_id)
    event_types = sorted({*left["event_counts"], *right["event_counts"]})
    return {
        "left": left,
        "right": right,
        "event_count_delta": right["event_count"] - left["event_count"],
        "event_type_delta": {
            event_type: right["event_counts"].get(event_type, 0)
            - left["event_counts"].get(event_type, 0)
            for event_type in event_types
        },
        "model_calls_added": [
            model_id for model_id in right["model_calls"] if model_id not in left["model_calls"]
        ],
        "patch_files_added": [
            file_path for file_path in right["patch_files"] if file_path not in left["patch_files"]
        ],
    }


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


def _print_diff(diff: dict[str, Any]) -> None:
    left = diff["left"]
    right = diff["right"]
    summary = Table(title="Session diff")
    summary.add_column("Field")
    summary.add_column("Left")
    summary.add_column("Right")
    summary.add_column("Delta")
    summary.add_row("Session", left["session_id"], right["session_id"], "")
    summary.add_row("Task", _clip(left.get("task") or "", 60), _clip(right.get("task") or "", 60), "")
    summary.add_row(
        "Events",
        str(left["event_count"]),
        str(right["event_count"]),
        str(diff["event_count_delta"]),
    )
    summary.add_row(
        "Model calls",
        str(len(left["model_calls"])),
        str(len(right["model_calls"])),
        str(len(right["model_calls"]) - len(left["model_calls"])),
    )
    summary.add_row(
        "Patch files",
        str(len(left["patch_files"])),
        str(len(right["patch_files"])),
        str(len(right["patch_files"]) - len(left["patch_files"])),
    )
    console.print(summary)

    events = Table(title="Event type delta")
    events.add_column("Type")
    events.add_column("Delta", justify="right")
    for event_type, delta in diff["event_type_delta"].items():
        events.add_row(event_type, str(delta))
    console.print(events)


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
    summary.add_row("Model prompt tokens", str(stats.model_prompt_tokens))
    summary.add_row("Model completion tokens", str(stats.model_completion_tokens))
    summary.add_row("Model total tokens", str(stats.model_total_tokens))
    summary.add_row("Model cached tokens", str(stats.model_cached_tokens))
    summary.add_row("Model cache miss tokens", str(stats.model_cache_miss_tokens))
    summary.add_row("Coding Plan allocations", str(stats.coding_plan_allocation_count))
    summary.add_row("Coding Plan baseline cost", str(stats.coding_plan_baseline_cost_score))
    summary.add_row("Coding Plan selected cost", str(stats.coding_plan_selected_cost_score))
    summary.add_row("Coding Plan estimated savings", str(stats.coding_plan_estimated_savings_score))
    summary.add_row("Coding Plan budget blocks", str(stats.coding_plan_budget_blocked_count))
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


def _session_digest(store: SessionStore, session_id: str) -> dict[str, Any]:
    summary = store.get_session(session_id)
    if summary is None:
        raise typer.BadParameter(f"unknown session id: {session_id}")
    events = store.list_events(session_id)
    event_counts = dict(Counter(event.event_type for event in events))
    model_calls = [
        str(event.payload["model_id"])
        for event in events
        if event.event_type == "model_called" and "model_id" in event.payload
    ]
    patch_files: list[str] = []
    for event in events:
        if event.event_type not in {"patch_created", "patch_applied"}:
            continue
        files = event.payload.get("files")
        if isinstance(files, list):
            patch_files.extend(str(file_path) for file_path in files)
    command_results = [
        event.payload.get("ok")
        for event in events
        if event.event_type == "command_result" and "ok" in event.payload
    ]
    return {
        **summary.to_dict(),
        "event_counts": event_counts,
        "event_count": len(events),
        "model_calls": model_calls,
        "patch_files": _dedupe(patch_files),
        "command_ok_count": sum(result is True for result in command_results),
        "command_failed_count": sum(result is False for result in command_results),
    }


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
