from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass(slots=True)
class CommitPreview:
    message: str
    files: list[str]
    staged_files: list[str]
    worktree: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "message": self.message,
            "files": self.files,
            "staged_files": self.staged_files,
            "worktree": str(self.worktree),
        }


def commit_cmd(
    message: str | None = typer.Argument(None, help="Commit message. Generated from git status when omitted."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    pathspecs: list[str] = typer.Option(
        [],
        "--path",
        "-p",
        help="Commit only this path. Repeat for multiple paths.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview message and files without staging or committing."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Create a local git commit from current workspace changes."""
    worktree = discover_worktree(workspace.resolve())
    preview = build_commit_preview(worktree, message=message, pathspecs=pathspecs)
    if dry_run:
        _print_preview(preview, output_json=output_json)
        return
    if not yes and not typer.confirm(f"Commit {len(preview.files)} file(s) with message: {preview.message!r}?"):
        console.print("Commit cancelled.")
        return
    stage_paths(worktree, pathspecs)
    staged_files = changed_files(worktree, staged=True)
    if not staged_files:
        raise typer.BadParameter("no staged changes to commit")
    final_preview = CommitPreview(
        message=preview.message,
        files=preview.files,
        staged_files=staged_files,
        worktree=worktree,
    )
    commit_hash = create_commit(worktree, preview.message, pathspecs=pathspecs)
    payload = {
        **final_preview.to_dict(),
        "commit": commit_hash,
    }
    if output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    console.print(f"Committed {commit_hash}: {preview.message}")


def discover_worktree(workspace: Path) -> Path:
    result = _git(workspace, ["rev-parse", "--show-toplevel"], check=False)
    if result.returncode != 0:
        raise typer.BadParameter(f"not a git repository: {workspace}")
    return Path(result.stdout.strip()).resolve()


def build_commit_preview(
    worktree: Path,
    *,
    message: str | None,
    pathspecs: list[str],
) -> CommitPreview:
    files = changed_files(worktree, pathspecs=pathspecs)
    if not files:
        scope = ", ".join(pathspecs) if pathspecs else "workspace"
        raise typer.BadParameter(f"no changes to commit in {scope}")
    staged_files = changed_files(worktree, pathspecs=pathspecs, staged=True)
    generated_message = message.strip() if message and message.strip() else generate_commit_message(files)
    return CommitPreview(
        message=generated_message,
        files=files,
        staged_files=staged_files,
        worktree=worktree,
    )


def changed_files(
    worktree: Path,
    *,
    pathspecs: list[str] | None = None,
    staged: bool = False,
) -> list[str]:
    args = ["diff", "--cached", "--name-only"] if staged else ["status", "--porcelain=v1", "--untracked-files=normal"]
    if pathspecs:
        args.extend(["--", *pathspecs])
    result = _git(worktree, args)
    if staged:
        return _dedupe([line.strip() for line in result.stdout.splitlines() if line.strip()])
    return _dedupe(_parse_status_files(result.stdout))


def stage_paths(worktree: Path, pathspecs: list[str]) -> None:
    args = ["add", "--all"]
    if pathspecs:
        args.extend(["--", *pathspecs])
    _git(worktree, args)


def create_commit(worktree: Path, message: str, *, pathspecs: list[str]) -> str:
    args = ["commit", "-m", message]
    if pathspecs:
        args.extend(["--", *pathspecs])
    _git(worktree, args)
    return _git(worktree, ["rev-parse", "--short", "HEAD"]).stdout.strip()


def generate_commit_message(files: list[str]) -> str:
    if len(files) == 1:
        path = files[0]
        return f"Update {Path(path).name}"
    roots = [_root_segment(path) for path in files]
    common_root = roots[0] if roots and all(root == roots[0] for root in roots) else None
    if common_root:
        return f"Update {common_root} files"
    return f"Update {len(files)} files"


def _parse_status_files(output: str) -> list[str]:
    files: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        path_text = line[3:]
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        files.append(path_text.strip().strip('"'))
    return files


def _root_segment(path: str) -> str:
    normalized = path.replace("\\", "/")
    if "/" not in normalized:
        return Path(normalized).stem or normalized
    return normalized.split("/", 1)[0]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _print_preview(preview: CommitPreview, *, output_json: bool) -> None:
    if output_json:
        print(json.dumps(preview.to_dict(), ensure_ascii=False, indent=2))
        return
    table = Table(title="Commit preview")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Message", preview.message)
    table.add_row("Files", "\n".join(preview.files))
    table.add_row("Already staged", "\n".join(preview.staged_files) or "none")
    console.print(table)


def _git(worktree: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
        raise typer.BadParameter(detail)
    return result
