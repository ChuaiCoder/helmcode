from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from helmcode.core.config import load_config, save_user_config
from helmcode.models.model_registry import ModelRegistry

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
    """Show configured model roles."""
    config = load_config()
    table = Table(title="Model roles")
    table.add_column("Role")
    table.add_column("Model ID")
    for role, model_id in sorted(config.model_roles.items()):
        table.add_row(role, model_id)
    if not config.model_roles:
        table.add_row("default", "[yellow]not configured[/yellow]")
    console.print(table)


@app.command("select")
def select_model(role: str = typer.Argument(...), model_id: str = typer.Argument(...)) -> None:
    """Set a model role to a provider-qualified model id."""
    config = load_config()
    config.model_roles[role] = model_id
    path = save_user_config(config)
    console.print(f"Set {role} -> {model_id} in {path}")
