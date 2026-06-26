from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helmcode.memory.coding_plan_budget import DEFAULT_BUDGET_KEY, CodingPlanBudgetLedger

console = Console()


def budget_cmd(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    key: str | None = typer.Option(None, "--key", help="Budget key. Defaults to all keys for status."),
    max_score: int | None = typer.Option(None, "--max-score", min=1, help="Show remaining score against this budget."),
    reset: bool = typer.Option(False, "--reset", help="Reset the selected budget key, or all keys if omitted."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip reset confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Inspect or reset cumulative Coding Plan budget usage."""
    ledger = CodingPlanBudgetLedger.for_workspace(workspace.resolve())
    if reset:
        _reset_budget(ledger, key=key, yes=yes, output_json=output_json)
        return
    statuses = [ledger.status(key)] if key else ledger.all_statuses()
    if not statuses:
        statuses = [ledger.status(DEFAULT_BUDGET_KEY)]
    payload = [status.to_dict(max_score=max_score) for status in statuses]
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_budget_table(payload)


def _reset_budget(
    ledger: CodingPlanBudgetLedger,
    *,
    key: str | None,
    yes: bool,
    output_json: bool,
) -> None:
    scope = key or "all budget keys"
    if not yes and not typer.confirm(f"Reset Coding Plan budget usage for {scope}?"):
        raise typer.Exit(1)
    removed = ledger.reset(key)
    if output_json:
        print(json.dumps({"removed": removed, "key": key}, ensure_ascii=False, indent=2))
        return
    console.print(f"Removed {removed} Coding Plan budget record(s) for {scope}.")


def _print_budget_table(rows: list[dict[str, object]]) -> None:
    table = Table(title="Coding Plan budget")
    table.add_column("Key")
    table.add_column("Allocations", justify="right")
    table.add_column("Selected", justify="right")
    table.add_column("Baseline", justify="right")
    table.add_column("Savings", justify="right")
    table.add_column("Blocked", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Warning")
    table.add_column("Updated")
    for row in rows:
        table.add_row(
            str(row["key"]),
            str(row["allocation_count"]),
            str(row["selected_cost_score"]),
            str(row["baseline_cost_score"]),
            str(row["estimated_savings_score"]),
            str(row["blocked_count"]),
            str(row.get("remaining_score", "")),
            "yes" if row.get("budget_warning") else "",
            str(row.get("updated_at") or ""),
        )
    console.print(table)
