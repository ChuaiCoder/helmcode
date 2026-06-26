from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.agent.allocation import AgentAssignment, CodingPlanTaskAllocator, TaskAllocation
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
    include_repair: bool = typer.Option(False, "--include-repair", help="Include a repair agent in the allocation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable allocation JSON."),
) -> None:
    """Show multi-agent assignment for a task without calling a provider."""
    allocation = build_allocation(
        task=task,
        workspace=workspace,
        routing=routing,
        model=model,
        include_repair=include_repair,
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
    include_repair: bool = False,
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
    )
    allocator = CodingPlanTaskAllocator(config, selector)
    return allocator.allocate(task, override_model_id=model, include_repair=include_repair)


def print_allocation(allocation: TaskAllocation) -> None:
    summary = Table(title="Coding Plan multi-agent allocation")
    summary.add_column("Field")
    summary.add_column("Value")
    summary.add_row("Task type", allocation.detected_task_type)
    summary.add_row("Complexity", allocation.complexity)
    summary.add_row("Strategy", allocation.strategy)
    summary.add_row("Estimated calls", str(allocation.estimated_calls))
    summary.add_row("Baseline cost score", str(allocation.baseline_cost_score))
    summary.add_row("Selected cost score", str(allocation.selected_cost_score))
    summary.add_row("Estimated savings score", str(allocation.estimated_savings_score))
    console.print(summary)

    table = Table(title="Assignments")
    table.add_column("Order")
    table.add_column("Agent")
    table.add_column("Task type")
    table.add_column("Model")
    table.add_column("Required")
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
    if assignment.quota_policy_id is None:
        return "unmetered"
    if assignment.quota_remaining is None:
        return assignment.quota_policy_id
    text = f"{assignment.quota_policy_id}: {assignment.quota_remaining} left"
    if assignment.quota_resets_at:
        text += f", resets {assignment.quota_resets_at}"
    return text
