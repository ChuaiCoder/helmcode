from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax

from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME
from helmcode.patch.apply import apply_unified_patch

console = Console()


def apply_last_patch(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without interactive prompt."),
) -> None:
    """Apply the last pending patch after showing the diff."""
    root = workspace.resolve()
    patch_path = root / SESSION_DIR_NAME / PENDING_PATCH_FILE
    if not patch_path.exists():
        console.print("[yellow]No pending patch found.[/yellow]")
        raise typer.Exit(code=1)
    patch = patch_path.read_text(encoding="utf-8")
    console.print(Syntax(patch, "diff"))
    if not yes and not typer.confirm("Apply this patch?"):
        console.print("Patch not applied.")
        raise typer.Exit(code=1)
    result = apply_unified_patch(root, patch)
    patch_path.unlink(missing_ok=True)
    console.print(f"Applied patch to: {', '.join(result.applied_files)}")
