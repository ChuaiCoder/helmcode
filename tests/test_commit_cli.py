from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.cli.commands.commit import generate_commit_message


def test_generate_commit_message_for_single_and_multiple_files() -> None:
    assert generate_commit_message(["README.md"]) == "Update README.md"
    assert generate_commit_message(["helmcode/a.py", "helmcode/b.py"]) == "Update helmcode files"
    assert generate_commit_message(["README.md", "helmcode/a.py"]) == "Update 2 files"


def test_commit_dry_run_outputs_generated_message(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\nchanged\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["commit", "--workspace", str(tmp_path), "--dry-run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["message"] == "Update README.md"
    assert payload["files"] == ["README.md"]
    assert _git(tmp_path, ["rev-list", "--count", "HEAD"]).stdout.strip() == "1"


def test_commit_creates_local_git_commit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\nchanged\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["commit", "Update docs", "--workspace", str(tmp_path), "--yes", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["message"] == "Update docs"
    assert payload["files"] == ["README.md"]
    assert _git(tmp_path, ["log", "-1", "--pretty=%s"]).stdout.strip() == "Update docs"
    assert _git(tmp_path, ["status", "--porcelain"]).stdout.strip() == ""


def test_commit_can_limit_to_pathspec(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("notes\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["commit", "--workspace", str(tmp_path), "--path", "README.md", "--yes", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["files"] == ["README.md"]
    assert _git(tmp_path, ["log", "-1", "--pretty=%s"]).stdout.strip() == "Update README.md"
    status = _git(tmp_path, ["status", "--porcelain"]).stdout
    assert "notes.md" in status
    assert "README.md" not in status


def test_commit_pathspec_does_not_include_other_staged_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("notes\n", encoding="utf-8")
    _git(tmp_path, ["add", "notes.md"])

    result = CliRunner().invoke(
        app,
        ["commit", "--workspace", str(tmp_path), "--path", "README.md", "--yes", "--json"],
    )

    assert result.exit_code == 0
    committed_files = _git(tmp_path, ["show", "--name-only", "--pretty=format:", "HEAD"]).stdout.splitlines()
    assert "README.md" in committed_files
    assert "notes.md" not in committed_files
    status = _git(tmp_path, ["status", "--porcelain"]).stdout
    assert "notes.md" in status


def _init_repo(path: Path) -> None:
    _git(path, ["init"])
    _git(path, ["config", "user.email", "helmcode@example.test"])
    _git(path, ["config", "user.name", "Helmcode Test"])
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, ["add", "README.md"])
    _git(path, ["commit", "-m", "Initial commit"])


def _git(path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
