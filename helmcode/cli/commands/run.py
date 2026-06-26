from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax

from helmcode.agent.runtime import AgentRuntime
from helmcode.agent.runner import RunOrchestrator
from helmcode.cli.commands import agents as agents_command
from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config
from helmcode.core.constants import MODEL_ROLE_CODING, MODEL_ROLE_PLANNING, MODEL_ROLE_REVIEW
from helmcode.core.error_handler import ErrorHandler, ErrorResponse
from helmcode.memory.coding_plan_budget import DEFAULT_BUDGET_KEY
from helmcode.memory.session_store import SessionStore
from helmcode.models.model_registry import ModelRegistry
from helmcode.models.quota import QuotaAwareSelector, QuotaLedger
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
    max_cost_score: int | None = typer.Option(
        None,
        "--max-cost-score",
        min=1,
        help="Block before provider calls if Coding Plan selected cost score exceeds this value.",
    ),
    session_budget_score: int | None = typer.Option(
        None,
        "--session-budget-score",
        min=1,
        help="Block before provider calls if cumulative Coding Plan selected cost exceeds this budget.",
    ),
    budget_key: str = typer.Option(
        DEFAULT_BUDGET_KEY,
        "--budget-key",
        help="Budget ledger key used with --session-budget-score.",
    ),
    no_preplan_cache: bool = typer.Option(
        False,
        "--no-preplan-cache",
        help="Disable cached scout/summarizer pre-plan findings for this run.",
    ),
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
                task=task,
                workspace=ws.root_path,
                routing=routing_mode,
                override_model_id=model,
                include_repair=not no_tests,
                max_cost_score=max_cost_score,
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
            block_on_allocation=True,
            allocation_include_repair=not no_tests,
            max_cost_score=max_cost_score,
            session_budget_score=session_budget_score,
            budget_key=budget_key,
            preplan_cache_enabled=not no_preplan_cache,
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
    task: str,
    workspace: Path,
    routing: str,
    override_model_id: str | None,
    include_repair: bool,
    max_cost_score: int | None,
) -> None:
    allocation = agents_command.build_allocation(
        task=task,
        workspace=workspace,
        routing=routing,
        model=override_model_id,
        include_repair=include_repair,
        max_cost_score=max_cost_score,
    )
    agents_command.print_allocation(allocation)
