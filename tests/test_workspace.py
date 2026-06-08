from pathlib import Path

from helmcode.context.workspace import Workspace


def test_workspace_detects_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "sample"
dependencies = ["typer", "pytest"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "sample").mkdir()
    (tmp_path / "sample" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    workspace = Workspace.discover(tmp_path)

    assert workspace.root_path == tmp_path.resolve()
    assert "Python" in workspace.detected_languages
    assert "pytest" in workspace.detected_frameworks
    assert "pytest" in workspace.test_commands
    assert workspace.package_manager in {"uv", "poetry", "pip"}


def test_workspace_detects_node_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "vitest", "build": "vite build"}, "dependencies": {"react": "^19.0.0"}}',
        encoding="utf-8",
    )

    workspace = Workspace.discover(tmp_path)

    assert "JavaScript" in workspace.detected_languages
    assert "React" in workspace.detected_frameworks
    assert workspace.package_manager in {"npm", "pnpm", "yarn"}
    assert any("test" in command for command in workspace.test_commands)
