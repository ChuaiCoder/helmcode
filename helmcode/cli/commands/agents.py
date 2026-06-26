from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.agent.allocation import AgentAssignment, CodingPlanTaskAllocator, TaskAllocation
from helmcode.cli.model_overrides import parse_model_overrides
from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config
from helmcode.models.quota import QuotaAwareSelector, QuotaLedger

console = Console()
app = typer.Typer(help="Plan quota-saving multi-agent task allocation.")


@app.command("plan")
def plan_agents(
    task: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    routing: str | None = typer.Option(None, "--routing", help="Model routing: fixed or quota."),
    model: str | None = typer.Option(None, "--model", help="Force all agents to this provider:model id."),
    preset: str = typer.Option(
        "balanced",
        "--preset",
        help="Coding Plan model preset: auto, economy, balanced, or pro.",
    ),
    role_model: list[str] | None = typer.Option(
        None,
        "--role-model",
        help=(
            "Override one agent/role/task route as KEY=provider:model. "
            "Repeatable; keys include coder, coding, planning, review, plan, code_patch."
        ),
    ),
    include_repair: bool = typer.Option(False, "--include-repair", help="Include a repair agent in the allocation."),
    max_cost_score: int | None = typer.Option(
        None,
        "--max-cost-score",
        min=1,
        help="Show whether selected cost score exceeds this budget.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable allocation JSON."),
) -> None:
    """Show multi-agent assignment for a task without calling a provider."""
    allocation = build_allocation(
        task=task,
        workspace=workspace,
        routing=routing,
        model=model,
        model_preset=preset,
        model_overrides=parse_model_overrides(role_model),
        include_repair=include_repair,
        max_cost_score=max_cost_score,
    )
    if output_json:
        print_allocation_json(allocation)
        return
    print_allocation(allocation)


@app.command("list")
def list_agents() -> None:
    """Show built-in and configured agent profiles."""
    config = load_config()
    allocator = CodingPlanTaskAllocator(
        config,
        QuotaAwareSelector(config, QuotaLedger(Path.cwd() / ".helmcode" / "quota_ledger.jsonl")),
    )
    table = Table(title="Agent profiles")
    table.add_column("Agent")
    table.add_column("Role")
    table.add_column("Task type")
    table.add_column("Model role")
    table.add_column("Required")
    table.add_column("Purpose")
    for profile in sorted(allocator.agent_profiles, key=lambda item: (item.order, item.id)):
        table.add_row(
            profile.id,
            profile.role,
            profile.task_type,
            profile.model_role,
            "yes" if profile.required else "no",
            profile.purpose,
        )
    console.print(table)


def build_allocation(
    *,
    task: str,
    workspace: Path,
    routing: str | None = None,
    model: str | None = None,
    model_preset: str | None = None,
    model_overrides: dict[str, str] | None = None,
    include_repair: bool = False,
    max_cost_score: int | None = None,
) -> TaskAllocation:
    config = load_config()
    routing_mode = routing or config.routing_mode
    if routing_mode == "recommend":
        routing_mode = "quota"
    if routing_mode not in {"fixed", "quota"}:
        raise typer.BadParameter("routing must be one of: fixed, quota")
    selector = QuotaAwareSelector(
        config,
        QuotaLedger.for_workspace(workspace.resolve()),
        routing_mode=routing_mode,
        model_preset=model_preset,
    )
    allocator = CodingPlanTaskAllocator(config, selector, workspace=Workspace.discover(workspace.resolve()))
    return allocator.allocate(
        task,
        override_model_id=model,
        model_overrides=model_overrides,
        include_repair=include_repair,
        max_cost_score=max_cost_score,
    )


def print_allocation(allocation: TaskAllocation) -> None:
    summary = Table(title="Coding Plan multi-agent allocation")
    summary.add_column("Field")
    summary.add_column("Value")
    summary.add_row("Task type", allocation.detected_task_type)
    summary.add_row("Complexity", allocation.complexity)
    summary.add_row("Strategy", allocation.strategy)
    summary.add_row("Model preset", allocation.model_preset)
    if allocation.effective_model_preset != allocation.model_preset:
        summary.add_row("Effective preset", allocation.effective_model_preset)
    summary.add_row("Estimated calls", str(allocation.estimated_calls))
    summary.add_row("Baseline model", allocation.baseline_model_id or "unknown")
    summary.add_row("Baseline calls", str(allocation.baseline_calls))
    summary.add_row("Baseline cost score", str(allocation.baseline_cost_score))
    summary.add_row("Selected cost score", str(allocation.selected_cost_score))
    summary.add_row("Required cost score", str(allocation.required_cost_score))
    summary.add_row("Optional cost score", str(allocation.optional_cost_score))
    if allocation.selected_cost_by_tier:
        tiers = ", ".join(
            f"{tier}={score}"
            for tier, score in sorted(allocation.selected_cost_by_tier.items())
        )
        summary.add_row("Selected by tier", tiers)
    if allocation.max_cost_score is not None:
        summary.add_row("Max cost score", str(allocation.max_cost_score))
        summary.add_row("Budget exceeded", "yes" if allocation.budget_exceeded else "no")
    summary.add_row("Estimated savings score", str(allocation.estimated_savings_score))
    console.print(summary)

    table = Table(title="Assignments")
    table.add_column("Order")
    table.add_column("Agent")
    table.add_column("Task type")
    table.add_column("Model")
    table.add_column("Required")
    table.add_column("Tier")
    table.add_column("Cost")
    table.add_column("Quota")
    table.add_column("Reason")
    for index, assignment in enumerate(allocation.assignments, start=1):
        quota = _quota_text(assignment)
        table.add_row(
            str(index),
            assignment.agent_id,
            assignment.task_type,
            assignment.model_id,
            "yes" if assignment.required else "no",
            assignment.model_cost_tier,
            str(assignment.estimated_cost_score),
            quota,
            assignment.reason,
        )
    console.print(table)

    if allocation.warnings:
        warnings = Table(title="Allocation warnings")
        warnings.add_column("Warning")
        for warning in allocation.warnings:
            warnings.add_row(warning)
        console.print(warnings)


def print_allocation_json(allocation: TaskAllocation) -> None:
    print(json.dumps(allocation.to_dict(), ensure_ascii=False, indent=2))


def _quota_text(assignment: AgentAssignment) -> str:
    if assignment.quota_reservations and len(assignment.quota_reservations) > 1:
        return "; ".join(_quota_reservation_text(reservation) for reservation in assignment.quota_reservations)
    if assignment.quota_policy_id is None:
        return "unmetered"
    if assignment.quota_remaining is None:
        return assignment.quota_policy_id
    text = f"{assignment.quota_policy_id}: {assignment.quota_remaining} left"
    if assignment.quota_reserved_amount != 1:
        unit = assignment.quota_unit or "unit"
        text += f", reserves {assignment.quota_reserved_amount} {unit}"
    if assignment.context_token_estimate and assignment.quota_unit == "token":
        text += f", includes {assignment.context_token_estimate} context token"
    if assignment.quota_remaining_after is not None:
        text += f", {assignment.quota_remaining_after} after allocation"
    if assignment.quota_resets_at:
        text += f", resets {assignment.quota_resets_at}"
    return text


def _quota_reservation_text(reservation: dict[str, object]) -> str:
    policy_id = str(reservation["policy_id"])
    unit = str(reservation["unit"])
    remaining = reservation.get("remaining")
    reserved_amount = int(reservation.get("reserved_amount") or 1)
    remaining_after = reservation.get("remaining_after")
    context_token_estimate = int(reservation.get("context_token_estimate") or 0)
    resets_at = reservation.get("resets_at")
    if remaining is None:
        text = f"{policy_id}/{unit}"
    else:
        text = f"{policy_id}/{unit}: {remaining} left"
    if reserved_amount != 1:
        text += f", reserves {reserved_amount} {unit}"
    if context_token_estimate and unit == "token":
        text += f", includes {context_token_estimate} context token"
    if remaining_after is not None:
        text += f", {remaining_after} after allocation"
    if resets_at:
        text += f", resets {resets_at}"
    return text
