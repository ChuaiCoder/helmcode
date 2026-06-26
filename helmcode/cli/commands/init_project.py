from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax

from helmcode.context.workspace import Workspace
from helmcode.memory.project_memory import ProjectMemory, build_agents_content

console = Console()


def init_cmd(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing AGENTS.md."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print generated AGENTS.md without writing."),
) -> None:
    """Initialize repo-scoped AGENTS.md project instructions."""
    ws = Workspace.discover(workspace)
    memory = ProjectMemory(ws.root_path)
    if dry_run:
        console.print(Syntax(build_agents_content(ws), "markdown"))
        return

    existing = memory.read_agents()
    if existing is not None and not force:
        console.print(f"[yellow]AGENTS.md already exists:[/yellow] {memory.agents_path}")
        console.print("Use --force to overwrite it.")
        raise typer.Exit(1)

    result = memory.init_agents(workspace=ws, overwrite=force)
    if result.overwritten:
        console.print(f"Updated project instructions: {result.path}")
    elif result.created:
        console.print(f"Created project instructions: {result.path}")
    else:
        console.print(f"Project instructions already exist: {result.path}")
