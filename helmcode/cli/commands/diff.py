from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax

from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME

console = Console()


def show_pending_diff(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
    """Show the pending Agent patch."""
    patch_path = workspace.resolve() / SESSION_DIR_NAME / PENDING_PATCH_FILE
    if not patch_path.exists():
        console.print("[yellow]No pending patch found.[/yellow]")
        raise typer.Exit(code=1)
    console.print(Syntax(patch_path.read_text(encoding="utf-8"), "diff"))
