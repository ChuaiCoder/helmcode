from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app


def test_init_command_creates_agents_md(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    result = CliRunner().invoke(app, ["init", "--workspace", str(tmp_path)])

    assert result.exit_code == 0
    agents_path = tmp_path / "AGENTS.md"
    assert agents_path.exists()
    content = agents_path.read_text(encoding="utf-8")
    assert "Languages: Python" in content
    assert "`pytest`" in content


def test_init_command_refuses_existing_agents_without_force(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("existing", encoding="utf-8")

    result = CliRunner().invoke(app, ["init", "--workspace", str(tmp_path)])

    assert result.exit_code == 1
    assert "AGENTS.md already exists" in result.output
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "existing"


def test_init_command_dry_run_does_not_write(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--workspace", str(tmp_path), "--dry-run"])

    assert result.exit_code == 0
    assert "# AGENTS.md" in result.output
    assert not (tmp_path / "AGENTS.md").exists()
