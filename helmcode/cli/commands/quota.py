from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.core.config import load_config
from helmcode.models.quota import ModelCallRecord, QuotaAwareSelector, QuotaLedger

console = Console()
app = typer.Typer(help="Inspect and manage local quota usage ledger.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def quota_main(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w", help="Workspace containing .helmcode."),
) -> None:
    """Show local quota status when no quota subcommand is provided."""
    if ctx.invoked_subcommand is None:
        status_quota(workspace=workspace)


@app.command("status")
def status_quota(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w", help="Workspace containing .helmcode."),
) -> None:
    """Show quota status for configured models."""
    config = load_config()
    selector = QuotaAwareSelector(config, QuotaLedger.for_workspace(workspace.resolve()))
    table = Table(title="Quota status")
    table.add_column("Model ID")
    table.add_column("Policy")
    table.add_column("Unit")
    table.add_column("Windows")
    for status in selector.status_for_configured_models():
        table.add_row(
            status.model_id,
            status.policy_id or "unmetered",
            status.unit,
            _quota_windows_text(status) or "no local quota policy",
        )
    console.print(table)


@app.command("history")
def history_quota(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w", help="Workspace containing .helmcode."),
    model_id: str | None = typer.Option(None, "--model", help="Filter by provider:model id."),
    unit: str | None = typer.Option(None, "--unit", help="Filter by quota unit."),
    role: str | None = typer.Option(None, "--role", help="Filter by agent/model role."),
    limit: int = typer.Option(20, "--limit", "-n", min=1, help="Maximum records to show."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show recent local quota ledger records."""
    records = _filtered_records(
        QuotaLedger.for_workspace(workspace.resolve()).load(),
        model_id=model_id,
        unit=unit,
        role=role,
    )
    records = sorted(records, key=lambda record: record.timestamp, reverse=True)[:limit]
    if output_json:
        print(json.dumps([record.to_json() for record in records], ensure_ascii=False, indent=2))
        return

    table = Table(title="Quota ledger history")
    table.add_column("Timestamp")
    table.add_column("Model")
    table.add_column("Role")
    table.add_column("Task")
    table.add_column("Unit")
    table.add_column("Amount")
    table.add_column("Session")
    table.add_column("Reason")
    for record in records:
        table.add_row(
            record.timestamp.isoformat(),
            record.model_id,
            record.role,
            record.task_type,
            record.unit,
            str(record.amount),
            record.session_id or "",
            record.reason,
        )
    console.print(table)


@app.command("reset")
def reset_quota(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w", help="Workspace containing .helmcode."),
    model_id: str | None = typer.Option(None, "--model", help="Reset only this provider:model id."),
    unit: str | None = typer.Option(None, "--unit", help="Reset only this quota unit."),
    role: str | None = typer.Option(None, "--role", help="Reset only this role."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Remove local quota ledger records, optionally filtered."""
    scope = _scope_text(model_id=model_id, unit=unit, role=role)
    if not yes and not typer.confirm(f"Reset local quota ledger records for {scope}?"):
        raise typer.Exit(1)
    removed = QuotaLedger.for_workspace(workspace.resolve()).clear(
        model_id=model_id,
        unit=unit,
        role=role,
    )
    console.print(f"Removed {removed} quota ledger record(s) for {scope}.")


def _filtered_records(
    records: list[ModelCallRecord],
    *,
    model_id: str | None,
    unit: str | None,
    role: str | None,
) -> list[ModelCallRecord]:
    return [
        record
        for record in records
        if (model_id is None or record.model_id == model_id)
        and (unit is None or record.unit == unit)
        and (role is None or record.role == role)
    ]


def _quota_windows_text(status) -> str:
    if status.policy_statuses:
        return "; ".join(
            f"{policy.policy_id}/{policy.unit}/{window.name}: "
            f"used {window.used}/{window.limit}, remaining {window.remaining}"
            + (f", restores {window.resets_at.isoformat()}" if window.resets_at else "")
            for policy in status.policy_statuses
            for window in policy.windows
        )
    return "; ".join(
        f"{window.name}: used {window.used}/{window.limit}, remaining {window.remaining}"
        + (f", restores {window.resets_at.isoformat()}" if window.resets_at else "")
        for window in status.windows
    )


def _scope_text(*, model_id: str | None, unit: str | None, role: str | None) -> str:
    filters = []
    if model_id:
        filters.append(f"model={model_id}")
    if unit:
        filters.append(f"unit={unit}")
    if role:
        filters.append(f"role={role}")
    return ", ".join(filters) if filters else "all models"
