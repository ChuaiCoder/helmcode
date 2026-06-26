from __future__ import annotations

from pathlib import Path

from helmcode.context.workspace import Workspace
from helmcode.memory.project_memory import ProjectMemory, build_agents_content


def test_build_agents_content_uses_detected_project_metadata(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    workspace = Workspace.discover(tmp_path)

    content = build_agents_content(workspace)

    assert "# AGENTS.md" in content
    assert "Languages: Python" in content
    assert "`pytest`" in content
    assert "helmcode agents plan <task>" in content


def test_project_memory_initializes_agents_without_overwriting(tmp_path: Path) -> None:
    workspace = Workspace.discover(tmp_path)
    memory = ProjectMemory(tmp_path)

    created = memory.init_agents(workspace=workspace)
    second = memory.init_agents(workspace=workspace)

    assert created.created is True
    assert created.path == tmp_path / "AGENTS.md"
    assert second.created is False
    assert second.overwritten is False
    assert memory.read_agents() == created.content


def test_project_memory_can_force_overwrite(tmp_path: Path) -> None:
    workspace = Workspace.discover(tmp_path)
    memory = ProjectMemory(tmp_path)
    (tmp_path / "AGENTS.md").write_text("old", encoding="utf-8")

    result = memory.init_agents(workspace=workspace, overwrite=True)

    assert result.created is False
    assert result.overwritten is True
    assert memory.read_agents() == result.content
    assert result.content != "old"
