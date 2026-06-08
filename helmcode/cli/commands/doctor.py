from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config

console = Console()


def doctor(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
    """Check local environment, repository, provider config, and test commands."""
    workspace = workspace.resolve()
    ws = Workspace.discover(workspace)
    config = load_config()

    table = Table(title="helmcode doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")

    _row(table, "workspace", True, str(ws.root_path))
    _row(table, "git installed", shutil.which("git") is not None, shutil.which("git") or "missing")
    _row(table, "git repository", ws.is_git_repo, str(ws.git_root) if ws.git_root else "not in git repo")
    _row(table, "ripgrep installed", shutil.which("rg") is not None, shutil.which("rg") or "missing")
    _row(table, "API providers", bool(config.providers), f"{len(config.providers)} configured")
    api_keys = [provider.id for provider in config.providers if os.getenv(provider.api_key_env)]
    _row(table, "API keys", bool(api_keys), ", ".join(api_keys) or "missing env vars")
    _row(table, "test command", bool(ws.test_commands), ", ".join(ws.test_commands) or "not detected")
    _row(table, "languages", bool(ws.detected_languages), ", ".join(ws.detected_languages) or "unknown")
    _row(table, "frameworks", bool(ws.detected_frameworks), ", ".join(ws.detected_frameworks) or "unknown")
    _row(table, "model reachability", _can_probe_models(config), "GET /models for configured providers")

    console.print(table)


def _row(table: Table, name: str, ok: bool, details: str) -> None:
    table.add_row(name, "[green]ok[/green]" if ok else "[yellow]warn[/yellow]", details)


def _can_probe_models(config) -> bool:
    if not config.providers:
        return False
    provider = config.providers[0]
    if not os.getenv(provider.api_key_env):
        return False
    try:
        import httpx

        response = httpx.get(
            provider.base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {os.getenv(provider.api_key_env)}"},
            timeout=5,
        )
    except Exception:
        return False
    return response.status_code < 500
