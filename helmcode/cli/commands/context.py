from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helmcode.context.context_builder import ContextBuilder, estimate_explicit_reference_tokens
from helmcode.context.workspace import Workspace

console = Console()


def context_cmd(
    task: str = typer.Argument(..., help="Task text used to build context. Supports @relative/path references."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w", help="Workspace root."),
    show_text: bool = typer.Option(False, "--show-text", help="Print the fitted model context text."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    max_file_chars: int = typer.Option(4_000, "--max-file-chars", min=1, help="Per-file excerpt character cap."),
) -> None:
    """Preview model context for a task without calling a provider."""
    workspace_info = Workspace.discover(workspace.resolve())
    builder = ContextBuilder(workspace_info, max_file_chars=max_file_chars)
    built = builder.build_for_task(task)
    explicit_token_estimate = estimate_explicit_reference_tokens(
        workspace_info,
        task,
        max_file_chars=max_file_chars,
    )
    payload = {
        "task": task,
        "workspace": str(workspace_info.root_path),
        "chars": len(built.text),
        "estimated_tokens": max(len(built.text) // 4, 1) if built.text else 0,
        "explicit_context_tokens": explicit_token_estimate,
        "files_considered": built.files_considered,
        "explicit_references": built.explicit_references or [],
        "warnings": built.warnings or [],
        "text": built.text if show_text else None,
    }
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    table = Table(title="Context preview")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Workspace", payload["workspace"])
    table.add_row("Characters", str(payload["chars"]))
    table.add_row("Estimated tokens", str(payload["estimated_tokens"]))
    table.add_row("Explicit context tokens", str(payload["explicit_context_tokens"]))
    table.add_row("Files considered", ", ".join(built.files_considered) or "none")
    table.add_row("Explicit references", ", ".join(built.explicit_references or []) or "none")
    if built.warnings:
        table.add_row("Warnings", "\n".join(built.warnings))
    console.print(table)
    if show_text:
        console.print(Panel(built.text, title="Fitted context"))
