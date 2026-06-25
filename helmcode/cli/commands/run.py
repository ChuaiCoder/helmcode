from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

from helmcode.agent.runtime import AgentRuntime
from helmcode.agent.runner import RunOrchestrator
from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config
from helmcode.core.constants import MODEL_ROLE_CODING, MODEL_ROLE_PLANNING, MODEL_ROLE_REVIEW
from helmcode.core.error_handler import ErrorHandler, ErrorResponse
from helmcode.memory.session_store import SessionStore
from helmcode.models.model_registry import ModelRegistry
from helmcode.models.quota import (
    TASK_CODE_PATCH,
    TASK_PLAN,
    TASK_REVIEW,
    QuotaAwareSelector,
    QuotaLedger,
)
from helmcode.models.selector import ModelSelector
from helmcode.safety.permissions import PermissionMode

console = Console()
error_handler = ErrorHandler(verbose=False)


def run_task(
    task: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve safe confirmations where allowed."),
    no_tests: bool = typer.Option(False, "--no-tests", help="Skip automatic test command after apply."),
    routing: str | None = typer.Option(None, "--routing", help="Model routing: fixed, quota, or recommend."),
    model: str | None = typer.Option(None, "--model", help="Force all model calls to this provider:model id."),
) -> None:
    """Run one task through plan, patch generation, diff confirmation, apply, and tests."""
    try:
        config = load_config()
        ws = Workspace.discover(workspace)
        routing_mode = _normalize_routing(routing or config.routing_mode)
        selector = ModelSelector(config.model_roles)
        planning_model_id = selector.select(MODEL_ROLE_PLANNING)
        coding_model_id = selector.select(MODEL_ROLE_CODING)
        review_model_id = selector.select(MODEL_ROLE_REVIEW)
        quota_selector = QuotaAwareSelector(
            config,
            QuotaLedger.for_workspace(ws.root_path),
            routing_mode=routing_mode,
        )
        if routing_mode == "recommend":
            _print_recommendations(
                quota_selector=quota_selector,
                task=task,
                planning_model_id=planning_model_id,
                coding_model_id=coding_model_id,
                review_model_id=review_model_id,
                override_model_id=model,
            )
            return

        registry = ModelRegistry.from_config(config)
        planning_provider = registry.provider_for_model(planning_model_id)
        coding_provider = registry.provider_for_model(coding_model_id)
        review_provider = registry.provider_for_model(review_model_id)
        session_store = SessionStore(ws.root_path)
        runtime = AgentRuntime(
            workspace=ws,
            selector=quota_selector,
            provider_resolver=registry.provider_for_model,
            session_store=session_store,
            override_model_id=model,
        )
        runner = RunOrchestrator(
            workspace=ws,
            provider=planning_provider,
            planning_model_id=planning_model_id,
            coding_model_id=coding_model_id,
            permission_mode=config.permission_mode,
            coding_provider=coding_provider,
            review_provider=review_provider,
            review_model_id=review_model_id,
            session_store=session_store,
            runtime=runtime,
        )
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Creating plan...", total=None)
            plan_state = runner.plan(task)
    except typer.Exit:
        raise
    except Exception as exc:
        error_response = error_handler.handle(exc)
        _print_error(error_response)
        raise typer.Exit(1)

    console.print(Panel(plan_state.plan, title="Plan"))
    plan_confirmed = yes or typer.confirm("Proceed to generate a patch from this plan?")
    if not plan_confirmed:
        console.print("Stopped before patch generation.")
        return

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task2 = progress.add_task("Generating patch...", total=None)
            result = runner.generate_patch_from_plan(plan_state)
    except typer.Exit:
        raise
    except Exception as exc:
        error_response = error_handler.handle(exc)
        _print_error(error_response)
        raise typer.Exit(1)

    console.print(Syntax(result.pending_patch, "diff"))
    if result.review:
        console.print(Panel(result.review, title="Review"))

    confirmed = yes or typer.confirm("Apply this patch?")
    if not confirmed:
        console.print("Patch stored for later. Inspect with `helmcode diff`, apply with `helmcode apply`.")
        return
    if not PermissionMode.normalize(config.permission_mode).can_apply_after_confirmation:
        console.print(
            f"Permission mode {config.permission_mode!r} stores patches only. "
            "Inspect with `helmcode diff`, apply with `helmcode apply`."
        )
        return

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task3 = progress.add_task("Applying patch...", total=None)
            apply_result = runner.apply_prepared(result, run_tests=not no_tests)
    except typer.Exit:
        raise
    except Exception as exc:
        error_response = error_handler.handle(exc)
        _print_error(error_response)
        raise typer.Exit(1)

    console.print(f"Applied patch to: {', '.join(apply_result.applied_files) or 'none'}")
    if apply_result.repair_attempts:
        console.print(f"Repair attempts: {apply_result.repair_attempts}")
    if apply_result.test_output:
        console.print(Panel(apply_result.test_output, title="Tests"))


def _print_error(error_response: ErrorResponse) -> None:
    console.print(Panel(f"[red]Error:[/red] {error_response.message}", title="Error"))
    if error_response.suggestion:
        console.print(f"[yellow]Suggestion:[/yellow] {error_response.suggestion}")
    if error_response.traceback:
        console.print(Panel(error_response.traceback, title="Traceback"))


def _normalize_routing(value: str) -> str:
    if value not in {"fixed", "quota", "recommend"}:
        raise typer.BadParameter("routing must be one of: fixed, quota, recommend")
    return value


def _print_recommendations(
    *,
    quota_selector: QuotaAwareSelector,
    task: str,
    planning_model_id: str,
    coding_model_id: str,
    review_model_id: str,
    override_model_id: str | None,
) -> None:
    table = Table(title="Model routing recommendation")
    table.add_column("Phase")
    table.add_column("Task type")
    table.add_column("Model")
    table.add_column("Reason")
    phases = [
        ("planning", TASK_PLAN, planning_model_id),
        ("coding", TASK_CODE_PATCH, coding_model_id),
        ("review", TASK_REVIEW, review_model_id),
    ]
    coding_choice: str | None = None
    for role, task_type, fallback in phases:
        selection = quota_selector.select(
            role=role,
            task_type=task_type,
            task=task,
            fallback_model_id=fallback,
            override_model_id=override_model_id,
            prefer_different_from=coding_choice if role == "review" else None,
        )
        if role == "coding":
            coding_choice = selection.model_id
        table.add_row(role, task_type, selection.model_id, selection.reason)
    console.print(table)
