from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.cli.model_overrides import parse_model_overrides
from helmcode.cli.commands import agents as agents_command
from helmcode.core.config import load_config, save_user_config
from helmcode.models.model_registry import ModelRegistry
from helmcode.models.quota import QuotaAwareSelector, QuotaLedger

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
        windows = _quota_windows_text(status)
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
    preset: str = typer.Option(
        "balanced",
        "--preset",
        help="Coding Plan model preset: economy, balanced, or pro.",
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
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable allocation JSON."),
) -> None:
    """Recommend the Coding Plan multi-agent route without calling a provider."""
    allocation = agents_command.build_allocation(
        task=task,
        workspace=workspace,
        routing="quota",
        model=model,
        model_preset=preset,
        model_overrides=parse_model_overrides(role_model),
        include_repair=include_repair,
        max_cost_score=max_cost_score,
    )
    if output_json:
        agents_command.print_allocation_json(allocation)
        return
    agents_command.print_allocation(allocation)


def _quota_windows_text(status) -> str:
    if status.policy_statuses:
        return "; ".join(
            f"{policy.policy_id}/{policy.unit}/{window.name}: "
            f"used {window.used}/{window.limit}, remaining {window.remaining}"
            + (f", restores {window.resets_at.isoformat()}" if window.resets_at else "")
            for policy in status.policy_statuses
            for window in policy.windows
        )
    return "; ".join(
        f"{window.name}: used {window.used}/{window.limit}, remaining {window.remaining}"
        + (f", restores {window.resets_at.isoformat()}" if window.resets_at else "")
        for window in status.windows
    )
