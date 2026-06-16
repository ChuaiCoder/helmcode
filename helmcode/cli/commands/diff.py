from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME
from helmcode.core.error_handler import ErrorHandler, ErrorResponse

console = Console()
error_handler = ErrorHandler(verbose=False)


def show_pending_diff(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
    """Show the pending Agent patch."""
    try:
        patch_path = workspace.resolve() / SESSION_DIR_NAME / PENDING_PATCH_FILE
        if not patch_path.exists():
            console.print("[yellow]No pending patch found.[/yellow]")
            raise typer.Exit(code=1)
        console.print(Syntax(patch_path.read_text(encoding="utf-8"), "diff"))
    except typer.Exit:
        raise
    except Exception as exc:
        error_response = error_handler.handle(exc)
        _print_error(error_response)
        raise typer.Exit(1)


def _print_error(error_response: ErrorResponse) -> None:
    console.print(Panel(f"[red]Error:[/red] {error_response.message}", title="Error"))
    if error_response.suggestion:
        console.print(f"[yellow]Suggestion:[/yellow] {error_response.suggestion}")
    if error_response.traceback:
        console.print(Panel(error_response.traceback, title="Traceback"))
