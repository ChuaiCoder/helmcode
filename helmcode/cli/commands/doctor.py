from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from helmcode.context.workspace import Workspace
from helmcode.core.config import HelmcodeConfig, load_config
from helmcode.core.error_handler import ErrorHandler, ErrorResponse
from helmcode.cli.commands.keys import build_key_status
from helmcode.models.quota import QuotaLedger

console = Console()
error_handler = ErrorHandler(verbose=False)


@dataclass(slots=True)
class DoctorCheck:
    name: str
    ok: bool
    details: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "details": self.details,
        }


def doctor(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    probe_models: bool = typer.Option(
        False,
        "--probe-models",
        help="Probe provider /models endpoints. Disabled by default to keep doctor local.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Check local environment, repository, provider config, and test commands."""
    try:
        if output_json:
            workspace = workspace.resolve()
            ws = Workspace.discover(workspace)
            config = load_config()
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Checking environment...", total=None)
                workspace = workspace.resolve()
                ws = Workspace.discover(workspace)
                config = load_config()

        checks = build_doctor_checks(ws, config, probe_models=probe_models)
        if output_json:
            print(json.dumps([check.to_dict() for check in checks], ensure_ascii=False, indent=2))
            return
        _print_checks(checks)
    except typer.Exit:
        raise
    except Exception as exc:
        error_response = error_handler.handle(exc)
        _print_error(error_response)
        raise typer.Exit(1)


def build_doctor_checks(
    ws: Workspace,
    config: HelmcodeConfig,
    *,
    probe_models: bool,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    checks.append(DoctorCheck("workspace", True, str(ws.root_path)))
    checks.append(DoctorCheck("python", True, sys.executable))
    checks.append(_path_check("helmcode npm wrapper", ws.root_path / "bin" / "helmcode.js"))
    checks.append(_path_check("package manifest", ws.root_path / "package.json"))
    checks.append(DoctorCheck("git installed", shutil.which("git") is not None, shutil.which("git") or "missing"))
    checks.append(
        DoctorCheck(
            "git repository",
            ws.is_git_repo,
            str(ws.git_root) if ws.git_root else "not in git repo",
        )
    )
    if ws.is_git_repo:
        checks.extend(_git_checks(ws.root_path))
    checks.append(DoctorCheck("ripgrep installed", shutil.which("rg") is not None, shutil.which("rg") or "missing"))
    checks.append(DoctorCheck("API providers", bool(config.providers), f"{len(config.providers)} configured"))
    key_status = build_key_status(config)
    set_keys = [status.provider_id for status in key_status if status.is_set]
    missing_keys = [f"{status.provider_id}:{status.api_key_env}" for status in key_status if not status.is_set]
    key_detail = f"set: {', '.join(set_keys) or 'none'}"
    if missing_keys:
        key_detail += f"; missing: {', '.join(missing_keys)}"
    checks.append(DoctorCheck("API keys", not missing_keys and bool(key_status), key_detail))
    checks.append(
        DoctorCheck("test command", bool(ws.test_commands), ", ".join(ws.test_commands) or "not detected")
    )
    checks.append(
        DoctorCheck("languages", bool(ws.detected_languages), ", ".join(ws.detected_languages) or "unknown")
    )
    checks.append(
        DoctorCheck("frameworks", bool(ws.detected_frameworks), ", ".join(ws.detected_frameworks) or "unknown")
    )
    checks.append(
        DoctorCheck("routing mode", config.routing_mode in {"fixed", "quota", "recommend"}, config.routing_mode)
    )
    checks.append(DoctorCheck("model roles", bool(config.model_roles), f"{len(config.model_roles)} configured"))
    checks.append(DoctorCheck("model profiles", True, f"{len(config.model_profiles)} configured"))
    checks.append(DoctorCheck("quota policies", True, f"{len(config.quota_policies)} configured"))
    ledger_path = QuotaLedger.for_workspace(ws.root_path).path
    checks.append(DoctorCheck("quota ledger", True, str(ledger_path)))
    if probe_models:
        checks.append(DoctorCheck("model reachability", _can_probe_models(config), "GET /models for configured providers"))
    else:
        checks.append(DoctorCheck("model reachability", True, "skipped; use --probe-models"))
    return checks


def _print_checks(checks: list[DoctorCheck]) -> None:
    table = Table(title="helmcode doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for check in checks:
        table.add_row(
            check.name,
            "[green]ok[/green]" if check.ok else "[yellow]warn[/yellow]",
            check.details,
        )
    console.print(table)


def _path_check(name: str, path: Path) -> DoctorCheck:
    return DoctorCheck(name, path.exists(), str(path) if path.exists() else f"missing: {path}")


def _git_checks(root_path: Path) -> list[DoctorCheck]:
    status = _run_git(root_path, ["status", "--porcelain=v1", "--branch"])
    if status is None:
        return [DoctorCheck("git status", False, "failed to run git status")]
    lines = status.splitlines()
    branch_line = lines[0] if lines else ""
    dirty_lines = [line for line in lines[1:] if line.strip()]
    ahead = _parse_ahead(branch_line)
    return [
        DoctorCheck("git dirty worktree", not dirty_lines, f"{len(dirty_lines)} changed file(s)"),
        DoctorCheck("git unpushed commits", ahead == 0, f"{ahead} ahead of upstream" if ahead else "none"),
    ]


def _run_git(root_path: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _parse_ahead(branch_line: str) -> int:
    marker = "ahead "
    if marker not in branch_line:
        return 0
    tail = branch_line.split(marker, 1)[1]
    digits = []
    for char in tail:
        if char.isdigit():
            digits.append(char)
            continue
        break
    return int("".join(digits) or "0")


def _can_probe_models(config) -> bool:
    if not config.providers:
        return False
    provider = config.providers[0]
    if not os.getenv(provider.api_key_env):
        return False
    try:
        import httpx

        response = httpx.get(
            provider.base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {os.getenv(provider.api_key_env)}"},
            timeout=5,
        )
    except Exception:
        return False
    return response.status_code < 500


def _print_error(error_response: ErrorResponse) -> None:
    console.print(Panel(f"[red]Error:[/red] {error_response.message}", title="Error"))
    if error_response.suggestion:
        console.print(f"[yellow]Suggestion:[/yellow] {error_response.suggestion}")
    if error_response.traceback:
        console.print(Panel(error_response.traceback, title="Traceback"))
