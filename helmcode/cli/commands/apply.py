from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import uuid4

import typer
from rich.console import Console
from rich.syntax import Syntax

from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME
from helmcode.core.config import load_config
from helmcode.core.exceptions import PermissionDenied
from helmcode.memory.session_store import SessionStore
from helmcode.patch.apply import apply_unified_patch
from helmcode.safety.permissions import PermissionMode

console = Console()


class EventStore(Protocol):
    def record(self, session_id: str, event_type: str, payload: dict[str, object]) -> None:
        pass


def apply_pending_patch(
    workspace: Path,
    permission_mode: str,
    session_store: EventStore | None = None,
):
    mode = PermissionMode.normalize(permission_mode)
    if mode is PermissionMode.READ_ONLY:
        raise PermissionDenied("read_only mode blocks patch application")
    root = workspace.resolve()
    patch_path = root / SESSION_DIR_NAME / PENDING_PATCH_FILE
    patch = patch_path.read_text(encoding="utf-8")
    result = apply_unified_patch(root, patch)
    patch_path.unlink(missing_ok=True)
    if session_store is not None:
        session_store.record(
            session_id=str(uuid4()),
            event_type="patch_applied",
            payload={"files": result.applied_files, "source": str(patch_path)},
        )
    return result


def apply_last_patch(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without interactive prompt."),
) -> None:
    """Apply the last pending patch after showing the diff."""
    root = workspace.resolve()
    config = load_config()
    patch_path = root / SESSION_DIR_NAME / PENDING_PATCH_FILE
    if not patch_path.exists():
        console.print("[yellow]No pending patch found.[/yellow]")
        raise typer.Exit(code=1)
    patch = patch_path.read_text(encoding="utf-8")
    console.print(Syntax(patch, "diff"))
    if not yes and not typer.confirm("Apply this patch?"):
        console.print("Patch not applied.")
        raise typer.Exit(code=1)
    try:
        result = apply_pending_patch(
            root,
            permission_mode=config.permission_mode,
            session_store=SessionStore(root),
        )
    except PermissionDenied as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"Applied patch to: {', '.join(result.applied_files)}")
