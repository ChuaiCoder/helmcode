from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from helmcode.cli.commands.plan import plan_task

console = Console()


def run_task(
    task: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve safe confirmations where allowed."),
) -> None:
    """Run one task. MVP generates the plan first and waits for explicit patch workflow."""
    plan_task(task, workspace)
    console.print(
        Panel(
            "MVP run mode stops after plan generation. Use generated patches with `helmcode diff` and `helmcode apply`.",
            title="Next",
        )
    )
