from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.agent.allocation import TaskAllocation
from helmcode.cli.commands import agents as agents_command
from helmcode.cli.model_overrides import parse_model_overrides
from helmcode.context.context_builder import ContextBuilder, estimate_explicit_reference_tokens
from helmcode.context.workspace import Workspace

console = Console()


def cost_cmd(
    task: str = typer.Argument(..., help="Task text used for context and Coding Plan allocation."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w", help="Workspace root."),
    routing: str | None = typer.Option(None, "--routing", help="Model routing: fixed, quota, or recommend."),
    model: str | None = typer.Option(None, "--model", help="Force all agents to this provider:model id."),
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
    include_repair: bool = typer.Option(False, "--include-repair", help="Include a repair agent in the allocation."),
    max_cost_score: int | None = typer.Option(
        None,
        "--max-cost-score",
        min=1,
        help="Show whether selected cost score exceeds this budget.",
    ),
    max_file_chars: int = typer.Option(4_000, "--max-file-chars", min=1, help="Per-file excerpt character cap."),
    max_explicit_files: int = typer.Option(
        8,
        "--max-explicit-files",
        min=1,
        help="Maximum files included from explicit @ references.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Preview context and Coding Plan cost without calling a provider."""
    workspace_info = Workspace.discover(workspace.resolve())
    built_context = ContextBuilder(
        workspace_info,
        max_file_chars=max_file_chars,
        max_explicit_files=max_explicit_files,
    ).build_for_task(task)
    allocation = agents_command.build_allocation(
        task=task,
        workspace=workspace_info.root_path,
        routing=routing,
        model=model,
        model_preset=preset,
        model_overrides=parse_model_overrides(role_model),
        include_repair=include_repair,
        max_cost_score=max_cost_score,
    )
    explicit_tokens = estimate_explicit_reference_tokens(
        workspace_info,
        task,
        max_file_chars=max_file_chars,
        max_explicit_files=max_explicit_files,
    )
    payload = _payload(
        task=task,
        workspace=workspace_info.root_path,
        context_text=built_context.text,
        explicit_context_tokens=explicit_tokens,
        files_considered=built_context.files_considered,
        explicit_references=built_context.explicit_references or [],
        warnings=built_context.warnings or [],
        allocation=allocation,
    )
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_cost(payload)


def _payload(
    *,
    task: str,
    workspace: Path,
    context_text: str,
    explicit_context_tokens: int,
    files_considered: list[str],
    explicit_references: list[str],
    warnings: list[str],
    allocation: TaskAllocation,
) -> dict[str, object]:
    return {
        "task": task,
        "workspace": str(workspace),
        "context": {
            "chars": len(context_text),
            "estimated_tokens": max(len(context_text) // 4, 1) if context_text else 0,
            "explicit_context_tokens": explicit_context_tokens,
            "files_considered": files_considered,
            "explicit_references": explicit_references,
            "warnings": warnings,
        },
        "allocation": allocation.to_dict(),
        "summary": {
            "detected_task_type": allocation.detected_task_type,
            "complexity": allocation.complexity,
            "model_preset": allocation.model_preset,
            "effective_model_preset": allocation.effective_model_preset,
            "estimated_calls": allocation.estimated_calls,
            "baseline_cost_score": allocation.baseline_cost_score,
            "selected_cost_score": allocation.selected_cost_score,
            "estimated_savings_score": allocation.estimated_savings_score,
            "budget_exceeded": allocation.budget_exceeded,
            "blocked": allocation.blocked,
        },
    }


def _print_cost(payload: dict[str, object]) -> None:
    summary = payload["summary"]
    context = payload["context"]
    allocation = payload["allocation"]
    table = Table(title="Cost preview")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Task type", str(summary["detected_task_type"]))
    table.add_row("Complexity", str(summary["complexity"]))
    table.add_row("Model preset", str(summary["model_preset"]))
    if summary["effective_model_preset"] != summary["model_preset"]:
        table.add_row("Effective preset", str(summary["effective_model_preset"]))
    table.add_row("Context tokens", str(context["estimated_tokens"]))
    table.add_row("Explicit context tokens", str(context["explicit_context_tokens"]))
    table.add_row("Files considered", ", ".join(context["files_considered"]) or "none")
    table.add_row("Estimated calls", str(summary["estimated_calls"]))
    table.add_row("Baseline cost score", str(summary["baseline_cost_score"]))
    table.add_row("Selected cost score", str(summary["selected_cost_score"]))
    table.add_row("Estimated savings score", str(summary["estimated_savings_score"]))
    table.add_row("Budget exceeded", "yes" if summary["budget_exceeded"] else "no")
    table.add_row("Blocked", "yes" if summary["blocked"] else "no")
    warnings = context.get("warnings") or allocation.get("warnings") or []
    if warnings:
        table.add_row("Warnings", "\n".join(str(warning) for warning in warnings))
    console.print(table)

    assignments = allocation.get("assignments") or []
    if assignments:
        detail = Table(title="Assignment cost")
        detail.add_column("Agent")
        detail.add_column("Model")
        detail.add_column("Cost")
        detail.add_column("Context tokens")
        detail.add_column("Quota")
        for assignment in assignments:
            detail.add_row(
                str(assignment["agent_id"]),
                str(assignment["model_id"]),
                str(assignment["estimated_cost_score"]),
                str(assignment.get("context_token_estimate") or 0),
                _quota_summary(assignment),
            )
        console.print(detail)


def _quota_summary(assignment: dict[str, object]) -> str:
    reservations = assignment.get("quota_reservations") or []
    if reservations:
        return "; ".join(
            f"{item['policy_id']}/{item['unit']}: reserves {item['reserved_amount']}"
            for item in reservations
        )
    policy_id = assignment.get("quota_policy_id")
    if policy_id:
        return str(policy_id)
    return "unmetered"
