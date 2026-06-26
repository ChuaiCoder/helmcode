from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from helmcode.memory.session_store import SessionEvent, SessionStore

console = Console()


def allocations_cmd(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    session_id: str | None = typer.Option(None, "--session", help="Filter by session id."),
    limit: int = typer.Option(20, "--limit", "-n", min=1, help="Maximum allocations to show."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List historical Coding Plan multi-agent allocations."""
    report = build_allocations_report(
        workspace=workspace.resolve(),
        session_id=session_id,
        limit=limit,
    )
    if output_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    _print_allocations(report)


def build_allocations_report(
    *,
    workspace: Path,
    session_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    store = SessionStore(workspace)
    events = store.list_events_by_type("task_allocated", session_id=session_id, limit=limit)
    allocations = [_allocation_payload(event) for event in events]
    return {
        "workspace": str(workspace),
        "session_id": session_id,
        "allocation_count": len(allocations),
        "baseline_cost_score": sum(_as_int(item["baseline_cost_score"]) for item in allocations),
        "selected_cost_score": sum(_as_int(item["selected_cost_score"]) for item in allocations),
        "estimated_savings_score": sum(_as_int(item["estimated_savings_score"]) for item in allocations),
        "budget_exceeded_count": sum(1 for item in allocations if item["budget_exceeded"]),
        "blocked_count": sum(1 for item in allocations if item["blocked"]),
        "allocations": allocations,
    }


def _allocation_payload(event: SessionEvent) -> dict[str, Any]:
    payload = event.payload
    assignments = _assignments(payload)
    return {
        "session_id": event.session_id,
        "created_at": event.created_at.isoformat(),
        "task": payload.get("task"),
        "detected_task_type": payload.get("detected_task_type"),
        "complexity": payload.get("complexity"),
        "strategy": payload.get("strategy"),
        "estimated_calls": _as_int(payload.get("estimated_calls")),
        "baseline_calls": _as_int(payload.get("baseline_calls")),
        "baseline_model_id": payload.get("baseline_model_id"),
        "baseline_cost_score": _as_int(payload.get("baseline_cost_score")),
        "selected_cost_score": _as_int(payload.get("selected_cost_score")),
        "estimated_savings_score": _as_int(payload.get("estimated_savings_score")),
        "max_cost_score": payload.get("max_cost_score"),
        "budget_exceeded": _as_bool(payload.get("budget_exceeded")),
        "blocked": _as_bool(payload.get("blocked")),
        "warnings": _strings(payload.get("warnings")),
        "agents": [str(item.get("agent_id") or "unknown") for item in assignments],
        "models": _dedupe(str(item.get("model_id") or "unknown") for item in assignments),
        "assignments": [_assignment_summary(item) for item in assignments],
    }


def _assignment_summary(assignment: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": assignment.get("agent_id"),
        "role": assignment.get("role"),
        "task_type": assignment.get("task_type"),
        "model_id": assignment.get("model_id"),
        "required": _as_bool(assignment.get("required")),
        "estimated_cost_score": _as_int(assignment.get("estimated_cost_score")),
        "model_cost_tier": assignment.get("model_cost_tier"),
        "context_token_estimate": _as_int(assignment.get("context_token_estimate")),
        "quota_reservations": assignment.get("quota_reservations") or [],
    }


def _print_allocations(report: dict[str, Any]) -> None:
    summary = Table(title="Coding Plan allocation history")
    summary.add_column("Metric")
    summary.add_column("Value")
    summary.add_row("Allocations", str(report["allocation_count"]))
    summary.add_row("Baseline cost score", str(report["baseline_cost_score"]))
    summary.add_row("Selected cost score", str(report["selected_cost_score"]))
    summary.add_row("Estimated savings score", str(report["estimated_savings_score"]))
    summary.add_row("Budget exceeded", str(report["budget_exceeded_count"]))
    summary.add_row("Blocked", str(report["blocked_count"]))
    if report.get("session_id"):
        summary.add_row("Session filter", str(report["session_id"]))
    console.print(summary)

    table = Table(title="Allocations")
    table.add_column("Time")
    table.add_column("Session")
    table.add_column("Task")
    table.add_column("Route")
    table.add_column("Cost")
    table.add_column("State")
    for item in report["allocations"]:
        state = "blocked" if item["blocked"] else "budget" if item["budget_exceeded"] else "ok"
        table.add_row(
            _clip(str(item["created_at"]), 19),
            _clip(str(item["session_id"]), 12),
            _clip(str(item.get("task") or ""), 28),
            _clip(_route_text(item["assignments"]), 32),
            f"{item['selected_cost_score']} / save {item['estimated_savings_score']}",
            state,
        )
    console.print(table)


def _assignments(allocation: dict[str, Any]) -> list[dict[str, Any]]:
    assignments = allocation.get("assignments")
    if not isinstance(assignments, list):
        return []
    return [item for item in assignments if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _route_text(assignments: list[dict[str, Any]]) -> str:
    if not assignments:
        return "none"
    return ", ".join(
        f"{assignment.get('agent_id') or 'unknown'}={assignment.get('model_id') or 'unknown'}"
        for assignment in assignments
    )


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _as_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_bool(value: Any) -> bool:
    return value is True
