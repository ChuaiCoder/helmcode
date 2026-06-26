from pathlib import Path

from helmcode.context.context_builder import ContextBuilder
from helmcode.context.workspace import Workspace
from helmcode.memory.skill_store import SkillStore


def test_context_builder_includes_relevant_file_content(tmp_path: Path) -> None:
    package_dir = tmp_path / "sample"
    package_dir.mkdir()
    (package_dir / "auth.py").write_text(
        "def login(username: str) -> str:\n"
        "    return f'hello {username}'\n",
        encoding="utf-8",
    )
    (package_dir / "billing.py").write_text(
        "def charge() -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )

    workspace = Workspace.discover(tmp_path)
    built = ContextBuilder(workspace).build_for_task("change the auth login greeting")

    assert "Relevant file excerpts:" in built.text
    assert "sample/auth.py" in built.text
    assert "def login" in built.text
    assert "--- sample/billing.py ---" not in built.text
    assert built.files_considered == ["sample/auth.py"]


def test_context_builder_skips_sensitive_relevant_files(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("public project docs\n", encoding="utf-8")

    workspace = Workspace.discover(tmp_path)
    built = ContextBuilder(workspace).build_for_task("inspect env token handling")

    assert "TOKEN=secret" not in built.text
    assert ".env" not in built.files_considered


def test_context_builder_injects_matching_project_skill(tmp_path: Path) -> None:
    SkillStore(tmp_path).add(
        skill_id="api-review",
        description="API review guidance",
        triggers=["api"],
        instructions="Check backward compatibility before editing API responses.",
    )
    workspace = Workspace.discover(tmp_path)

    built = ContextBuilder(workspace).build_for_task("change api response shape")

    assert "Matched skills:" in built.text
    assert "### api-review" in built.text
    assert "Check backward compatibility" in built.text
