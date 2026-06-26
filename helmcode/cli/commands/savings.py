from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from helmcode.memory.session_store import SessionEvent, SessionStore

console = Console()


def savings_cmd(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        min=1,
        help="Limit report to the newest N Coding Plan allocations.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show historical Coding Plan cost savings from local session events."""
    report = build_savings_report(workspace=workspace.resolve(), limit=limit)
    if output_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    _print_report(report)


def build_savings_report(*, workspace: Path, limit: int | None = None) -> dict[str, Any]:
    store = SessionStore(workspace)
    events = store.list_events_by_type("task_allocated", limit=limit)
    allocations = [event.payload for event in events]
    by_agent: dict[str, dict[str, Any]] = defaultdict(_group)
    by_role: dict[str, dict[str, Any]] = defaultdict(_group)
    by_model: dict[str, dict[str, Any]] = defaultdict(_group)
    by_task_type: dict[str, dict[str, Any]] = defaultdict(_group)
    total_assignments = 0
    total_required = 0
    total_optional = 0
    total_context_tokens = 0

    for allocation in allocations:
        for assignment in _assignments(allocation):
            total_assignments += 1
            if _as_bool(assignment.get("required")):
                total_required += 1
            else:
                total_optional += 1
            total_context_tokens += _as_int(assignment.get("context_token_estimate"))
            _add_assignment(by_agent[str(assignment.get("agent_id") or "unknown")], assignment)
            _add_assignment(by_role[str(assignment.get("role") or "unknown")], assignment)
            _add_assignment(by_model[str(assignment.get("model_id") or "unknown")], assignment)
            _add_assignment(by_task_type[str(assignment.get("task_type") or "unknown")], assignment)

    baseline_cost = sum(_as_int(item.get("baseline_cost_score")) for item in allocations)
    selected_cost = sum(_as_int(item.get("selected_cost_score")) for item in allocations)
    savings_score = sum(
        _as_int(item.get("estimated_savings_score"))
        for item in allocations
    )
    if savings_score == 0 and baseline_cost > selected_cost:
        savings_score = baseline_cost - selected_cost
    allocation_count = len(allocations)
    return {
        "workspace": str(workspace),
        "allocation_count": allocation_count,
        "estimated_calls": sum(_as_int(item.get("estimated_calls")) for item in allocations),
        "baseline_calls": sum(_as_int(item.get("baseline_calls")) for item in allocations),
        "assignment_count": total_assignments,
        "required_assignment_count": total_required,
        "optional_assignment_count": total_optional,
        "context_token_estimate": total_context_tokens,
        "baseline_cost_score": baseline_cost,
        "selected_cost_score": selected_cost,
        "estimated_savings_score": savings_score,
        "savings_rate": _savings_rate(baseline_cost, savings_score),
        "budget_exceeded_count": sum(
            1 for item in allocations if _as_bool(item.get("budget_exceeded"))
        ),
        "blocked_count": sum(1 for item in allocations if _as_bool(item.get("blocked"))),
        "by_agent": _sorted_groups(by_agent),
        "by_role": _sorted_groups(by_role),
        "by_model": _sorted_groups(by_model),
        "by_task_type": _sorted_groups(by_task_type),
        "recent_allocations": [_allocation_summary(event) for event in events],
    }


def _print_report(report: dict[str, Any]) -> None:
    summary = Table(title="Coding Plan savings")
    summary.add_column("Metric")
    summary.add_column("Value")
    summary.add_row("Allocations", str(report["allocation_count"]))
    summary.add_row("Assignments", str(report["assignment_count"]))
    summary.add_row("Baseline calls", str(report["baseline_calls"]))
    summary.add_row("Selected calls", str(report["estimated_calls"]))
    summary.add_row("Baseline cost score", str(report["baseline_cost_score"]))
    summary.add_row("Selected cost score", str(report["selected_cost_score"]))
    summary.add_row("Estimated savings score", str(report["estimated_savings_score"]))
    summary.add_row("Savings rate", f"{report['savings_rate']:.1%}")
    summary.add_row("Context token estimate", str(report["context_token_estimate"]))
    summary.add_row("Budget exceeded", str(report["budget_exceeded_count"]))
    summary.add_row("Blocked allocations", str(report["blocked_count"]))
    console.print(summary)

    _print_group_table("Cost by agent", report["by_agent"])
    _print_group_table("Cost by model", report["by_model"])


def _print_group_table(title: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    table = Table(title=title)
    table.add_column("Name")
    table.add_column("Assignments", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Required", justify="right")
    table.add_column("Optional", justify="right")
    table.add_column("Context tokens", justify="right")
    table.add_column("Quota reserved")
    for row in rows:
        table.add_row(
            str(row["name"]),
            str(row["assignment_count"]),
            str(row["cost_score"]),
            str(row["required_assignment_count"]),
            str(row["optional_assignment_count"]),
            str(row["context_token_estimate"]),
            _quota_text(row["quota_reserved"]),
        )
    console.print(table)


def _allocation_summary(event: SessionEvent) -> dict[str, Any]:
    payload = event.payload
    return {
        "session_id": event.session_id,
        "created_at": event.created_at.isoformat(),
        "task": payload.get("task"),
        "detected_task_type": payload.get("detected_task_type"),
        "complexity": payload.get("complexity"),
        "baseline_cost_score": _as_int(payload.get("baseline_cost_score")),
        "selected_cost_score": _as_int(payload.get("selected_cost_score")),
        "estimated_savings_score": _as_int(payload.get("estimated_savings_score")),
        "budget_exceeded": _as_bool(payload.get("budget_exceeded")),
        "blocked": _as_bool(payload.get("blocked")),
    }


def _assignments(allocation: dict[str, Any]) -> list[dict[str, Any]]:
    assignments = allocation.get("assignments")
    if not isinstance(assignments, list):
        return []
    return [item for item in assignments if isinstance(item, dict)]


def _group() -> dict[str, Any]:
    return {
        "assignment_count": 0,
        "required_assignment_count": 0,
        "optional_assignment_count": 0,
        "cost_score": 0,
        "context_token_estimate": 0,
        "quota_reserved": defaultdict(int),
    }


def _add_assignment(group: dict[str, Any], assignment: dict[str, Any]) -> None:
    group["assignment_count"] += 1
    group["cost_score"] += _as_int(assignment.get("estimated_cost_score"))
    group["context_token_estimate"] += _as_int(assignment.get("context_token_estimate"))
    if _as_bool(assignment.get("required")):
        group["required_assignment_count"] += 1
    else:
        group["optional_assignment_count"] += 1
    for reservation in _quota_reservations(assignment):
        unit = str(reservation.get("unit") or "request")
        group["quota_reserved"][unit] += _as_int(reservation.get("reserved_amount"), default=1)


def _quota_reservations(assignment: dict[str, Any]) -> list[dict[str, Any]]:
    reservations = assignment.get("quota_reservations")
    if isinstance(reservations, list) and reservations:
        return [item for item in reservations if isinstance(item, dict)]
    policy_id = assignment.get("quota_policy_id")
    if policy_id:
        return [
            {
                "unit": assignment.get("quota_unit") or "request",
                "reserved_amount": assignment.get("quota_reserved_amount") or 1,
            }
        ]
    return []


def _sorted_groups(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, values in groups.items():
        quota_reserved = {
            str(unit): int(amount)
            for unit, amount in values["quota_reserved"].items()
        }
        rows.append(
            {
                "name": name,
                "assignment_count": values["assignment_count"],
                "required_assignment_count": values["required_assignment_count"],
                "optional_assignment_count": values["optional_assignment_count"],
                "cost_score": values["cost_score"],
                "context_token_estimate": values["context_token_estimate"],
                "quota_reserved": quota_reserved,
            }
        )
    return sorted(rows, key=lambda item: (-item["cost_score"], item["name"]))


def _quota_text(values: dict[str, int]) -> str:
    if not values:
        return "unmetered"
    return ", ".join(f"{unit}={amount}" for unit, amount in sorted(values.items()))


def _savings_rate(baseline_cost: int, savings_score: int) -> float:
    if baseline_cost <= 0:
        return 0.0
    return savings_score / baseline_cost


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
