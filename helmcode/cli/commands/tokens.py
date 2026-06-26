from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from helmcode.memory.session_store import SessionEvent, SessionStore

console = Console()


def tokens_cmd(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    session_id: str | None = typer.Option(None, "--session", help="Filter by session id."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        min=1,
        help="Limit to newest N model calls and allocations.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show model token usage and Coding Plan token estimates from local events."""
    report = build_tokens_report(
        workspace=workspace.resolve(),
        session_id=session_id,
        limit=limit,
    )
    if output_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    _print_tokens(report)


def build_tokens_report(
    *,
    workspace: Path,
    session_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    store = SessionStore(workspace)
    model_events = store.list_events_by_type("model_called", session_id=session_id, limit=limit)
    allocation_events = store.list_events_by_type("task_allocated", session_id=session_id, limit=limit)
    model_calls = [_model_call(event) for event in model_events]
    allocation_estimates = [_allocation_estimate(event) for event in allocation_events]
    by_model: dict[str, dict[str, Any]] = defaultdict(_usage_group)
    by_role: dict[str, dict[str, Any]] = defaultdict(_usage_group)
    by_task_type: dict[str, dict[str, Any]] = defaultdict(_usage_group)
    for call in model_calls:
        _add_usage(by_model[str(call["model_id"])], call)
        _add_usage(by_role[str(call["role"])], call)
        _add_usage(by_task_type[str(call["task_type"])], call)
    allocation_context_tokens = sum(
        _as_int(item["context_token_estimate"])
        for item in allocation_estimates
    )
    allocation_reserved_tokens = sum(
        _as_int(item["quota_token_reserved"])
        for item in allocation_estimates
    )
    summary = _usage_summary(model_calls)
    summary.update(
        {
            "allocation_count": len(allocation_estimates),
            "allocation_context_token_estimate": allocation_context_tokens,
            "allocation_quota_token_reserved": allocation_reserved_tokens,
        }
    )
    return {
        "workspace": str(workspace),
        "session_id": session_id,
        "summary": summary,
        "by_model": _sorted_usage_groups(by_model),
        "by_role": _sorted_usage_groups(by_role),
        "by_task_type": _sorted_usage_groups(by_task_type),
        "recent_model_calls": model_calls,
        "allocation_estimates": allocation_estimates,
    }


def _model_call(event: SessionEvent) -> dict[str, Any]:
    payload = event.payload
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens = _as_int(usage.get("prompt_tokens"))
    completion_tokens = _as_int(usage.get("completion_tokens"))
    total_tokens = _as_int(usage.get("total_tokens"))
    cached_tokens = _as_int(usage.get("cached_tokens"))
    cache_miss_tokens = _as_int(usage.get("cache_miss_tokens"))
    if cache_miss_tokens == 0 and prompt_tokens >= cached_tokens:
        cache_miss_tokens = prompt_tokens - cached_tokens
    return {
        "session_id": event.session_id,
        "created_at": event.created_at.isoformat(),
        "role": payload.get("role") or "unknown",
        "task_type": payload.get("task_type") or "unknown",
        "model_id": payload.get("model_id") or "unknown",
        "routing_mode": payload.get("routing_mode") or "unknown",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cache_miss_tokens": cache_miss_tokens,
    }


def _allocation_estimate(event: SessionEvent) -> dict[str, Any]:
    payload = event.payload
    context_tokens = 0
    quota_token_reserved = 0
    assignments = payload.get("assignments")
    if isinstance(assignments, list):
        for assignment in assignments:
            if not isinstance(assignment, dict):
                continue
            context_tokens += _as_int(assignment.get("context_token_estimate"))
            quota_token_reserved += _reserved_tokens(assignment)
    return {
        "session_id": event.session_id,
        "created_at": event.created_at.isoformat(),
        "task": payload.get("task"),
        "detected_task_type": payload.get("detected_task_type"),
        "selected_cost_score": _as_int(payload.get("selected_cost_score")),
        "context_token_estimate": context_tokens,
        "quota_token_reserved": quota_token_reserved,
    }


def _reserved_tokens(assignment: dict[str, Any]) -> int:
    reservations = assignment.get("quota_reservations")
    if isinstance(reservations, list):
        return sum(
            _as_int(item.get("reserved_amount"))
            for item in reservations
            if isinstance(item, dict) and item.get("unit") == "token"
        )
    if assignment.get("quota_unit") == "token":
        return _as_int(assignment.get("quota_reserved_amount"))
    return 0


def _usage_summary(model_calls: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = sum(_as_int(item["prompt_tokens"]) for item in model_calls)
    completion = sum(_as_int(item["completion_tokens"]) for item in model_calls)
    total = sum(_as_int(item["total_tokens"]) for item in model_calls)
    cached = sum(_as_int(item["cached_tokens"]) for item in model_calls)
    cache_miss = sum(_as_int(item["cache_miss_tokens"]) for item in model_calls)
    if total == 0:
        total = prompt + completion
    return {
        "model_call_count": len(model_calls),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
        "cache_miss_tokens": cache_miss,
        "cache_hit_rate": cached / prompt if prompt > 0 else 0.0,
    }


def _usage_group() -> dict[str, Any]:
    return {
        "model_call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "cache_miss_tokens": 0,
    }


def _add_usage(group: dict[str, Any], call: dict[str, Any]) -> None:
    group["model_call_count"] += 1
    for key in [
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
        "cache_miss_tokens",
    ]:
        group[key] += _as_int(call[key])


def _sorted_usage_groups(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, values in groups.items():
        prompt_tokens = _as_int(values["prompt_tokens"])
        cached_tokens = _as_int(values["cached_tokens"])
        rows.append(
            {
                "name": name,
                **values,
                "cache_hit_rate": cached_tokens / prompt_tokens if prompt_tokens > 0 else 0.0,
            }
        )
    return sorted(rows, key=lambda item: (-_as_int(item["total_tokens"]), item["name"]))


def _print_tokens(report: dict[str, Any]) -> None:
    summary = report["summary"]
    table = Table(title="Token usage")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Model calls", str(summary["model_call_count"]))
    table.add_row("Prompt tokens", str(summary["prompt_tokens"]))
    table.add_row("Completion tokens", str(summary["completion_tokens"]))
    table.add_row("Total tokens", str(summary["total_tokens"]))
    table.add_row("Cached tokens", str(summary["cached_tokens"]))
    table.add_row("Cache miss tokens", str(summary["cache_miss_tokens"]))
    table.add_row("Cache hit rate", f"{summary['cache_hit_rate']:.1%}")
    table.add_row("Coding Plan allocations", str(summary["allocation_count"]))
    table.add_row("Context token estimate", str(summary["allocation_context_token_estimate"]))
    table.add_row("Quota token reserved", str(summary["allocation_quota_token_reserved"]))
    if report.get("session_id"):
        table.add_row("Session filter", str(report["session_id"]))
    console.print(table)
    _print_group("Tokens by model", report["by_model"])
    _print_group("Tokens by role", report["by_role"])


def _print_group(title: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    table = Table(title=title)
    table.add_column("Name")
    table.add_column("Calls", justify="right")
    table.add_column("Prompt", justify="right")
    table.add_column("Completion", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Cached", justify="right")
    table.add_column("Hit rate", justify="right")
    for row in rows:
        table.add_row(
            str(row["name"]),
            str(row["model_call_count"]),
            str(row["prompt_tokens"]),
            str(row["completion_tokens"]),
            str(row["total_tokens"]),
            str(row["cached_tokens"]),
            f"{row['cache_hit_rate']:.1%}",
        )
    console.print(table)


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
