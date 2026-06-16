from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax

from helmcode.agent.runner import RunOrchestrator
from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config
from helmcode.core.constants import MODEL_ROLE_CODING, MODEL_ROLE_PLANNING, MODEL_ROLE_REVIEW
from helmcode.core.error_handler import ErrorHandler, ErrorResponse
from helmcode.memory.session_store import SessionStore
from helmcode.models.model_registry import ModelRegistry
from helmcode.models.selector import ModelSelector
from helmcode.safety.permissions import PermissionMode

console = Console()
error_handler = ErrorHandler(verbose=False)


def run_task(
    task: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve safe confirmations where allowed."),
    no_tests: bool = typer.Option(False, "--no-tests", help="Skip automatic test command after apply."),
) -> None:
    """Run one task through plan, patch generation, diff confirmation, apply, and tests."""
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task1 = progress.add_task("Loading configuration...", total=None)
            config = load_config()
            ws = Workspace.discover(workspace)
            selector = ModelSelector(config.model_roles)
            planning_model_id = selector.select(MODEL_ROLE_PLANNING)
            coding_model_id = selector.select(MODEL_ROLE_CODING)
            review_model_id = selector.select(MODEL_ROLE_REVIEW)
            registry = ModelRegistry.from_config(config)
            planning_provider = registry.provider_for_model(planning_model_id)
            coding_provider = registry.provider_for_model(coding_model_id)
            review_provider = registry.provider_for_model(review_model_id)
            runner = RunOrchestrator(
                workspace=ws,
                provider=planning_provider,
                planning_model_id=planning_model_id,
                coding_model_id=coding_model_id,
                permission_mode=config.permission_mode,
                coding_provider=coding_provider,
                review_provider=review_provider,
                review_model_id=review_model_id,
                session_store=SessionStore(ws.root_path),
            )
            progress.update(task1, description="Creating plan...")
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
