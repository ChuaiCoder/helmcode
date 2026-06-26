from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app


def test_context_command_outputs_json_summary(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("project overview\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["context", "explain @README.md", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["task"] == "explain @README.md"
    assert payload["explicit_references"] == ["README.md"]
    assert payload["files_considered"] == ["README.md"]
    assert payload["explicit_context_tokens"] > 0
    assert payload["text"] is None


def test_context_command_show_text_includes_fitted_context(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("project overview\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["context", "explain @README.md", "--workspace", str(tmp_path), "--show-text"],
    )

    assert result.exit_code == 0
    assert "Context preview" in result.output
    assert "Fitted context" in result.output
    assert "project overview" in result.output


def test_context_command_reports_reference_warnings(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["context", "explain @missing.py", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["warnings"] == ["Skipped @missing.py: file not found"]


def test_context_command_outputs_directory_references(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "a.py").write_text("a" * 80, encoding="utf-8")
    (source_dir / "b.py").write_text("b" * 40, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["context", "explain @src", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["explicit_references"] == ["src/a.py", "src/b.py"]
    assert payload["files_considered"] == ["src/a.py", "src/b.py"]
    assert payload["explicit_context_tokens"] == 30


def test_context_command_limits_directory_references(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "a.py").write_text("a\n", encoding="utf-8")
    (source_dir / "b.py").write_text("b\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "context",
            "explain @src",
            "--workspace",
            str(tmp_path),
            "--max-explicit-files",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["explicit_references"] == ["src/a.py"]
    assert payload["warnings"] == ["Truncated @src: only included first 1 files"]
