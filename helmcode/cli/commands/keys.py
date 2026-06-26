from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.core.config import HelmcodeConfig, load_config

console = Console()


@dataclass(slots=True)
class ProviderKeyStatus:
    provider_id: str
    api_key_env: str
    is_set: bool
    base_url: str
    roles: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "api_key_env": self.api_key_env,
            "is_set": self.is_set,
            "base_url": self.base_url,
            "roles": self.roles,
        }


def keys_cmd(
    config_path: Path | None = typer.Option(None, "--config", help="Use a specific config file."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show provider key readiness without printing secret values."""
    config = load_config(config_path)
    statuses = build_key_status(config)
    if output_json:
        print(json.dumps([status.to_dict() for status in statuses], ensure_ascii=False, indent=2))
        return
    print_key_status(statuses)


def build_key_status(config: HelmcodeConfig) -> list[ProviderKeyStatus]:
    roles_by_provider: dict[str, list[str]] = {provider.id: [] for provider in config.providers}
    for role, model_id in sorted(config.model_roles.items()):
        provider_id = model_id.split(":", 1)[0]
        if provider_id in roles_by_provider:
            roles_by_provider[provider_id].append(role)
    return [
        ProviderKeyStatus(
            provider_id=provider.id,
            api_key_env=provider.api_key_env,
            is_set=bool(os.getenv(provider.api_key_env)),
            base_url=provider.base_url,
            roles=roles_by_provider.get(provider.id, []),
        )
        for provider in config.providers
    ]


def print_key_status(statuses: list[ProviderKeyStatus]) -> None:
    table = Table(title="Provider keys")
    table.add_column("Provider")
    table.add_column("Env")
    table.add_column("Status")
    table.add_column("Roles")
    table.add_column("Base URL")
    for status in statuses:
        table.add_row(
            status.provider_id,
            status.api_key_env,
            "[green]set[/green]" if status.is_set else "[yellow]missing[/yellow]",
            ", ".join(status.roles) or "none",
            status.base_url,
        )
    console.print(table)
