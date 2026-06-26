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
from helmcode.memory.coding_plan_budget import DEFAULT_BUDGET_KEY, CodingPlanBudgetLedger
from helmcode.models.quota import (
    MODEL_PRESET_AUTO,
    MODEL_PRESET_BALANCED,
    MODEL_PRESET_ECONOMY,
    MODEL_PRESET_PRO,
    normalize_model_preset,
)

console = Console()
PRESET_COMPARISON = [
    MODEL_PRESET_AUTO,
    MODEL_PRESET_ECONOMY,
    MODEL_PRESET_BALANCED,
    MODEL_PRESET_PRO,
]


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
    session_budget_score: int | None = typer.Option(
        None,
        "--session-budget-score",
        min=1,
        help="Preview whether each route would exceed this cumulative Coding Plan budget.",
    ),
    budget_key: str = typer.Option("default", "--budget-key", help="Budget ledger key for session budget."),
    compare_presets: bool = typer.Option(
        False,
        "--compare-presets",
        help="Compare quota routes for auto, economy, balanced, and pro.",
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
        session_budget_score=session_budget_score,
        budget_key=budget_key,
        compare_presets=compare_presets,
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
    session_budget_score: int | None = None,
    budget_key: str = DEFAULT_BUDGET_KEY,
    compare_presets: bool = False,
) -> dict[str, Any]:
    workspace_info = Workspace.discover(workspace)
    requested_preset = normalize_model_preset(model_preset)
    budget_status = (
        CodingPlanBudgetLedger.for_workspace(workspace_info.root_path).status(budget_key)
        if session_budget_score is not None
        else None
    )
    route_specs: list[tuple[str, str, str | None, str]] = [
        ("fixed", "fixed", None, requested_preset),
    ]
    if compare_presets:
        route_specs.extend(
            (f"quota:{preset}", "quota", None, preset)
            for preset in PRESET_COMPARISON
        )
    else:
        route_specs.append(("quota", "quota", None, requested_preset))
    if model:
        route_specs.append(("forced", "quota", model, requested_preset))
    routes = [
        _route_payload(
            label=label,
            routing=routing,
            model=route_model,
            model_preset=route_preset,
            model_overrides=model_overrides,
            task=task,
            workspace=workspace_info.root_path,
            include_repair=include_repair,
            max_cost_score=max_cost_score,
            session_budget_score=session_budget_score,
            budget_key=budget_key,
            current_session_selected_cost_score=(
                budget_status.selected_cost_score
                if budget_status is not None
                else None
            ),
            warning_threshold_score=(
                budget_status.warning_threshold(session_budget_score)
                if budget_status is not None
                else None
            ),
        )
        for label, routing, route_model, route_preset in route_specs
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
        "session_budget_score": session_budget_score,
        "budget_key": budget_key,
        "current_session_selected_cost_score": (
            budget_status.selected_cost_score
            if budget_status is not None
            else None
        ),
        "forced_model": model,
        "model_preset": requested_preset,
        "compare_presets": compare_presets,
        "presets_compared": PRESET_COMPARISON if compare_presets else [],
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
    session_budget_score: int | None,
    budget_key: str,
    current_session_selected_cost_score: int | None,
    warning_threshold_score: int | None,
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
    session_budget = _session_budget_preview(
        allocation=allocation,
        budget_key=budget_key,
        session_budget_score=session_budget_score,
        current_selected_cost_score=current_session_selected_cost_score,
        warning_threshold_score=warning_threshold_score,
    )
    summary = _summary(allocation)
    if session_budget is not None:
        summary.update(
            {
                "session_budget_exceeded": session_budget["budget_exceeded"],
                "session_budget_warning": session_budget["budget_warning"],
                "projected_session_selected_cost_score": session_budget["projected_selected_cost_score"],
                "remaining_session_score_after": session_budget["remaining_score_after"],
            }
        )
    return {
        "route": label,
        "routing": routing,
        "forced_model": model,
        "model_preset": allocation.model_preset,
        "effective_model_preset": allocation.effective_model_preset,
        "model_overrides": model_overrides or {},
        "ok": True,
        "error": None,
        "summary": summary,
        "session_budget": session_budget,
        "allocation": allocation.to_dict(),
        "assignment_route": [
            f"{assignment.agent_id}={assignment.model_id}"
            for assignment in allocation.assignments
        ],
    }


def _session_budget_preview(
    *,
    allocation: TaskAllocation,
    budget_key: str,
    session_budget_score: int | None,
    current_selected_cost_score: int | None,
    warning_threshold_score: int | None,
) -> dict[str, Any] | None:
    if session_budget_score is None or current_selected_cost_score is None:
        return None
    projected = current_selected_cost_score + allocation.selected_cost_score
    return {
        "budget_key": budget_key,
        "session_budget_score": session_budget_score,
        "current_selected_cost_score": current_selected_cost_score,
        "selected_cost_score": allocation.selected_cost_score,
        "projected_selected_cost_score": projected,
        "remaining_score_after": max(session_budget_score - projected, 0),
        "warning_threshold_score": warning_threshold_score,
        "budget_warning": (
            warning_threshold_score is not None
            and projected >= warning_threshold_score
        ),
        "budget_exceeded": projected > session_budget_score,
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
    if summary.get("session_budget_exceeded"):
        return "session-budget"
    if summary.get("session_budget_warning"):
        return "ok warn"
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
        and not route["summary"].get("session_budget_exceeded")
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
    if route == "quota" or route.startswith("quota:"):
        return 0
    return {"fixed": 1, "forced": 2}.get(route, 99)
