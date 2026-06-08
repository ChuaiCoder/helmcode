from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config

console = Console()


def start_interactive(workspace_path: Path) -> None:
    """Start an interactive shell-like MVP session."""
    config = load_config()
    workspace = Workspace.discover(workspace_path)
    table = Table(title="helmcode")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Project", str(workspace.root_path))
    table.add_row("Git branch", workspace.current_branch or "not a git repo")
    table.add_row("Languages", ", ".join(workspace.detected_languages) or "unknown")
    table.add_row("Frameworks", ", ".join(workspace.detected_frameworks) or "unknown")
    table.add_row("Tests", ", ".join(workspace.test_commands) or "not detected")
    table.add_row("Permission mode", config.permission_mode)
    table.add_row("Models", ", ".join(sorted(config.model_roles)) or "not configured")
    console.print(table)
    console.print(Panel("Type a task, or /exit to quit. Use `helmcode plan \"task\"` for non-interactive planning."))
    while True:
        try:
            task = console.input("[bold]helmcode> [/bold]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if task in {"/exit", "exit", "quit", ""}:
            return
        console.print(
            "[yellow]Interactive execution loop is in MVP mode. Run `helmcode plan "
            f"{task!r}` to create a plan.[/yellow]"
        )
