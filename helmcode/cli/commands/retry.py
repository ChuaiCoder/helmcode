from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from helmcode.cli.commands import plan as plan_command
from helmcode.cli.commands import run as run_command
from helmcode.memory.session_store import SessionStore, SessionTask

console = Console()


def retry_cmd(
    session_id: str | None = typer.Argument(None, help="Session id to retry. Defaults to latest task."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    mode: str = typer.Option("recommend", "--mode", help="Retry mode: recommend, plan, or run."),
    routing: str | None = typer.Option(None, "--routing", help="Model routing: fixed, quota, or recommend."),
    model: str | None = typer.Option(None, "--model", help="Force a provider:model id."),
    max_cost_score: int | None = typer.Option(
        None,
        "--max-cost-score",
        min=1,
        help="Block plan/run before provider calls if selected Coding Plan cost exceeds this value.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve safe confirmations where allowed."),
    no_tests: bool = typer.Option(False, "--no-tests", help="Skip tests for run mode."),
    no_preplan_cache: bool = typer.Option(
        False,
        "--no-preplan-cache",
        help="Disable cached scout/summarizer pre-plan findings.",
    ),
) -> None:
    """Retry the latest recorded task or the latest task from a specific session."""
    task = resolve_retry_task(workspace.resolve(), session_id)
    console.print(f"Retrying {task.session_id}: {_clip(task.task, 120)}")
    execute_retry_task(
        task.task,
        workspace=workspace.resolve(),
        mode=mode,
        routing=routing,
        model=model,
        max_cost_score=max_cost_score,
        yes=yes,
        no_tests=no_tests,
        no_preplan_cache=no_preplan_cache,
    )


def resolve_retry_task(workspace: Path, session_id: str | None = None) -> SessionTask:
    store = SessionStore(workspace)
    task = store.latest_task(session_id=session_id)
    if task is None:
        detail = f"session {session_id}" if session_id else "recent sessions"
        raise typer.BadParameter(f"no retryable user task found in {detail}")
    return task


def execute_retry_task(
    task: str,
    *,
    workspace: Path,
    mode: str,
    routing: str | None,
    model: str | None,
    max_cost_score: int | None,
    yes: bool,
    no_tests: bool,
    no_preplan_cache: bool,
) -> None:
    normalized_mode = _normalize_mode(mode)
    normalized_routing = _normalize_routing(routing) if routing is not None else None
    if normalized_mode == "recommend":
        run_command.run_task(
            task=task,
            workspace=workspace,
            yes=yes,
            no_tests=no_tests,
            routing="recommend",
            model=model,
            max_cost_score=max_cost_score,
            no_preplan_cache=no_preplan_cache,
        )
        return
    if normalized_mode == "plan":
        plan_command.plan_task(
            task=task,
            workspace=workspace,
            routing=normalized_routing,
            model=model,
            max_cost_score=max_cost_score,
            no_preplan_cache=no_preplan_cache,
        )
        return
    run_command.run_task(
        task=task,
        workspace=workspace,
        yes=yes,
        no_tests=no_tests,
        routing=normalized_routing,
        model=model,
        max_cost_score=max_cost_score,
        no_preplan_cache=no_preplan_cache,
    )


def _normalize_mode(value: str) -> str:
    if value not in {"recommend", "plan", "run"}:
        raise typer.BadParameter("mode must be one of: recommend, plan, run")
    return value


def _normalize_routing(value: str) -> str:
    if value not in {"fixed", "quota", "recommend"}:
        raise typer.BadParameter("routing must be one of: fixed, quota, recommend")
    return value


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
