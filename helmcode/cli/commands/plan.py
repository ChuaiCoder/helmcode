from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from helmcode.agent.runtime import AgentRuntime
from helmcode.agent.runner import RunOrchestrator
from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config
from helmcode.core.constants import MODEL_ROLE_CODING, MODEL_ROLE_PLANNING, MODEL_ROLE_REVIEW
from helmcode.memory.session_store import SessionStore
from helmcode.models.model_registry import ModelRegistry
from helmcode.models.quota import QuotaAwareSelector, QuotaLedger
from helmcode.models.selector import ModelSelector

console = Console()


def plan_task(
    task: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    routing: str | None = typer.Option(None, "--routing", help="Model routing: fixed or quota."),
    model: str | None = typer.Option(None, "--model", help="Force planning to this provider:model id."),
    max_cost_score: int | None = typer.Option(
        None,
        "--max-cost-score",
        min=1,
        help="Block before provider calls if Coding Plan selected cost score exceeds this value.",
    ),
    no_preplan_cache: bool = typer.Option(
        False,
        "--no-preplan-cache",
        help="Disable cached scout/summarizer pre-plan findings for this plan.",
    ),
) -> None:
    """Generate a plan without modifying files."""
    config = load_config()
    ws = Workspace.discover(workspace)
    routing_mode = routing or config.routing_mode
    if routing_mode == "recommend":
        routing_mode = "quota"
    if routing_mode not in {"fixed", "quota"}:
        raise typer.BadParameter("routing must be one of: fixed, quota")
    selector = ModelSelector(config.model_roles)
    planning_model_id = selector.select(MODEL_ROLE_PLANNING)
    coding_model_id = selector.select(MODEL_ROLE_CODING)
    review_model_id = selector.select(MODEL_ROLE_REVIEW)
    registry = ModelRegistry.from_config(config)
    planning_provider = registry.provider_for_model(planning_model_id)
    coding_provider = registry.provider_for_model(coding_model_id)
    review_provider = registry.provider_for_model(review_model_id)
    session_store = SessionStore(ws.root_path)
    quota_selector = QuotaAwareSelector(
        config,
        QuotaLedger.for_workspace(ws.root_path),
        routing_mode=routing_mode,
    )
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
        block_on_allocation=False,
        allocation_include_repair=False,
        max_cost_score=max_cost_score,
        preplan_cache_enabled=not no_preplan_cache,
    )
    result = runner.plan(task)
    console.print(Panel(result.plan, title="Plan"))
