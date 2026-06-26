from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from helmcode.agent.allocation import TaskAllocation
from helmcode.cli.commands import agents as agents_command
from helmcode.cli.model_overrides import parse_model_overrides
from helmcode.context.workspace import Workspace

console = Console()


def routes_cmd(
    task: str = typer.Argument(..., help="Task text used for Coding Plan route comparison."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Also compare a forced provider:model route.",
    ),
    preset: str = typer.Option(
        "balanced",
        "--preset",
        help="Coding Plan model preset: auto, economy, balanced, or pro.",
    ),
    role_model: list[str] | None = typer.Option(
        None,
        "--role-model",
        help="Override one agent/role/task route as KEY=provider:model. Repeatable.",
    ),
    include_repair: bool = typer.Option(False, "--include-repair", help="Include a repair agent."),
    max_cost_score: int | None = typer.Option(
        None,
        "--max-cost-score",
        min=1,
        help="Show whether each route exceeds this Coding Plan budget.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Compare fixed, quota-aware, and optional forced-model Coding Plan routes."""
    payload = build_routes_report(
        task=task,
        workspace=workspace.resolve(),
        model=model,
        model_preset=preset,
        model_overrides=parse_model_overrides(role_model),
        include_repair=include_repair,
        max_cost_score=max_cost_score,
    )
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_routes(payload)


def build_routes_report(
    *,
    task: str,
    workspace: Path,
    model: str | None = None,
    model_preset: str | None = None,
    model_overrides: dict[str, str] | None = None,
    include_repair: bool = False,
    max_cost_score: int | None = None,
) -> dict[str, Any]:
    workspace_info = Workspace.discover(workspace)
    route_specs: list[tuple[str, str, str | None]] = [
        ("fixed", "fixed", None),
        ("quota", "quota", None),
    ]
    if model:
        route_specs.append(("forced", "quota", model))
    routes = [
        _route_payload(
            label=label,
            routing=routing,
            model=route_model,
            model_preset=model_preset,
            model_overrides=model_overrides,
            task=task,
            workspace=workspace_info.root_path,
            include_repair=include_repair,
            max_cost_score=max_cost_score,
        )
        for label, routing, route_model in route_specs
    ]
    fixed_cost = _selected_cost(_find_route(routes, "fixed"))
    for route in routes:
        selected_cost = _selected_cost(route)
        route["selected_cost_delta_vs_fixed"] = (
            selected_cost - fixed_cost
            if fixed_cost is not None and selected_cost is not None
            else None
        )
        route["savings_vs_fixed"] = (
            max(fixed_cost - selected_cost, 0)
            if fixed_cost is not None and selected_cost is not None
            else None
        )
    best = _best_route(routes)
    return {
        "task": task,
        "workspace": str(workspace_info.root_path),
        "include_repair": include_repair,
        "max_cost_score": max_cost_score,
        "forced_model": model,
        "model_preset": model_preset or "balanced",
        "model_overrides": model_overrides or {},
        "best_route": best["route"] if best else None,
        "routes": routes,
    }


def _route_payload(
    *,
    label: str,
    routing: str,
    model: str | None,
    model_preset: str | None,
    model_overrides: dict[str, str] | None,
    task: str,
    workspace: Path,
    include_repair: bool,
    max_cost_score: int | None,
) -> dict[str, Any]:
    try:
        allocation = agents_command.build_allocation(
            task=task,
            workspace=workspace,
            routing=routing,
            model=model,
            model_preset=model_preset,
            model_overrides=model_overrides,
            include_repair=include_repair,
            max_cost_score=max_cost_score,
        )
    except Exception as exc:
        return {
            "route": label,
            "routing": routing,
            "forced_model": model,
            "model_preset": model_preset or "balanced",
            "effective_model_preset": None,
            "model_overrides": model_overrides or {},
            "ok": False,
            "error": str(exc),
            "summary": None,
            "allocation": None,
            "assignment_route": [],
        }
    return {
        "route": label,
        "routing": routing,
        "forced_model": model,
        "model_preset": allocation.model_preset,
        "effective_model_preset": allocation.effective_model_preset,
        "model_overrides": model_overrides or {},
        "ok": True,
        "error": None,
        "summary": _summary(allocation),
        "allocation": allocation.to_dict(),
        "assignment_route": [
            f"{assignment.agent_id}={assignment.model_id}"
            for assignment in allocation.assignments
        ],
    }


def _summary(allocation: TaskAllocation) -> dict[str, Any]:
    return {
        "detected_task_type": allocation.detected_task_type,
        "complexity": allocation.complexity,
        "strategy": allocation.strategy,
        "model_preset": allocation.model_preset,
        "effective_model_preset": allocation.effective_model_preset,
        "estimated_calls": allocation.estimated_calls,
        "baseline_cost_score": allocation.baseline_cost_score,
        "selected_cost_score": allocation.selected_cost_score,
        "estimated_savings_score": allocation.estimated_savings_score,
        "required_cost_score": allocation.required_cost_score,
        "optional_cost_score": allocation.optional_cost_score,
        "budget_exceeded": allocation.budget_exceeded,
        "blocked": allocation.blocked,
        "warnings": allocation.warnings,
    }


def _print_routes(payload: dict[str, Any]) -> None:
    table = Table(title="Coding Plan route comparison")
    table.add_column("Route")
    table.add_column("State")
    table.add_column("Calls", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Save vs fixed", justify="right")
    table.add_column("Assignment route")
    for route in payload["routes"]:
        summary = route.get("summary")
        if not route["ok"]:
            table.add_row(
                str(route["route"]),
                "error",
                "-",
                "-",
                "-",
                str(route["error"]),
            )
            continue
        state = _route_state(summary)
        if route["route"] == payload.get("best_route"):
            state += " best"
        table.add_row(
            str(route["route"]),
            state,
            str(summary["estimated_calls"]),
            str(summary["selected_cost_score"]),
            _optional_int(route.get("savings_vs_fixed")),
            ", ".join(route["assignment_route"]) or "none",
        )
    console.print(table)


def _route_state(summary: dict[str, Any]) -> str:
    if summary.get("blocked"):
        return "blocked"
    if summary.get("budget_exceeded"):
        return "budget"
    return "ok"


def _find_route(routes: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((route for route in routes if route["route"] == name), None)


def _selected_cost(route: dict[str, Any] | None) -> int | None:
    if not route or not route.get("ok"):
        return None
    summary = route.get("summary")
    if not isinstance(summary, dict):
        return None
    value = summary.get("selected_cost_score")
    return int(value) if isinstance(value, int) else None


def _best_route(routes: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        route
        for route in routes
        if route.get("ok")
        and isinstance(route.get("summary"), dict)
        and not route["summary"].get("blocked")
        and not route["summary"].get("budget_exceeded")
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda route: (
            int(route["summary"]["selected_cost_score"]),
            int(route["summary"]["estimated_calls"]),
            _route_priority(str(route["route"])),
        ),
    )


def _optional_int(value: object) -> str:
    if value is None:
        return "-"
    return str(value)


def _route_priority(route: str) -> int:
    return {"quota": 0, "fixed": 1, "forced": 2}.get(route, 99)
