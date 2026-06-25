from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.core.config import load_config, save_user_config
from helmcode.core.constants import MODEL_ROLE_CODING, MODEL_ROLE_PLANNING, MODEL_ROLE_REVIEW
from helmcode.models.model_registry import ModelRegistry
from helmcode.models.quota import (
    TASK_CODE_PATCH,
    TASK_PLAN,
    TASK_REVIEW,
    QuotaAwareSelector,
    QuotaLedger,
)
from helmcode.models.selector import ModelSelector

console = Console()
app = typer.Typer(help="Manage provider model discovery and model roles.")


@app.command("sync")
def sync_models() -> None:
    """Fetch model lists from configured providers."""
    config = load_config()
    registry = ModelRegistry.from_config(config)
    models = registry.sync()
    table = Table(title="Synced models")
    table.add_column("Model ID")
    table.add_column("Provider")
    for model in models:
        table.add_row(model.id, model.provider_id)
    console.print(table)


@app.command("list")
def list_models() -> None:
    """Show configured model roles and local model profiles."""
    config = load_config()
    table = Table(title="Model roles")
    table.add_column("Role")
    table.add_column("Model ID")
    table.add_column("Profile")
    for role, model_id in sorted(config.model_roles.items()):
        profile = next((profile for profile in config.model_profiles if profile.id == model_id), None)
        profile_text = ", ".join(profile.labels) if profile else ""
        table.add_row(role, model_id, profile_text)
    if not config.model_roles:
        table.add_row("default", "[yellow]not configured[/yellow]", "")
    console.print(table)

    if config.model_profiles:
        profiles = Table(title="Model profiles")
        profiles.add_column("Model ID")
        profiles.add_column("Preferred for")
        profiles.add_column("Cost")
        profiles.add_column("Fallbacks")
        for profile in config.model_profiles:
            profiles.add_row(
                profile.id,
                ", ".join(profile.preferred_for),
                profile.cost_tier,
                ", ".join(profile.fallback_models),
            )
        console.print(profiles)


@app.command("select")
def select_model(role: str = typer.Argument(...), model_id: str = typer.Argument(...)) -> None:
    """Set a model role to a provider-qualified model id."""
    config = load_config()
    config.model_roles[role] = model_id
    path = save_user_config(config)
    console.print(f"Set {role} -> {model_id} in {path}")


@app.command("status")
def model_status(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
    """Show local quota estimates for configured models."""
    config = load_config()
    selector = QuotaAwareSelector(config, QuotaLedger.for_workspace(workspace.resolve()))
    table = Table(title="Model quota status")
    table.add_column("Model ID")
    table.add_column("Policy")
    table.add_column("Unit")
    table.add_column("Windows")
    for status in selector.status_for_configured_models():
        windows = "; ".join(
            f"{window.name}: used {window.used}/{window.limit}, remaining {window.remaining}"
            + (f", restores {window.resets_at.isoformat()}" if window.resets_at else "")
            for window in status.windows
        )
        table.add_row(
            status.model_id,
            status.policy_id or "unmetered",
            status.unit,
            windows or "no local quota policy",
        )
    console.print(table)


@app.command("recommend")
def recommend_models(
    task: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    model: str | None = typer.Option(None, "--model", help="Force all phases to this provider:model id."),
) -> None:
    """Recommend models for a task without calling a provider."""
    config = load_config()
    selector = QuotaAwareSelector(config, QuotaLedger.for_workspace(workspace.resolve()))
    role_selector = ModelSelector(config.model_roles)
    table = Table(title="Model routing recommendation")
    table.add_column("Phase")
    table.add_column("Task type")
    table.add_column("Model")
    table.add_column("Reason")
    phases = [
        ("planning", TASK_PLAN, role_selector.select(MODEL_ROLE_PLANNING)),
        ("coding", TASK_CODE_PATCH, role_selector.select(MODEL_ROLE_CODING)),
        ("review", TASK_REVIEW, role_selector.select(MODEL_ROLE_REVIEW)),
    ]
    coding_model: str | None = None
    for role, task_type, fallback_model_id in phases:
        selection = selector.select(
            role=role,
            task_type=task_type,
            task=task,
            fallback_model_id=fallback_model_id,
            override_model_id=model,
            prefer_different_from=coding_model if role == "review" else None,
        )
        if role == "coding":
            coding_model = selection.model_id
        table.add_row(role, task_type, selection.model_id, selection.reason)
    console.print(table)
