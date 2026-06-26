from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from helmcode.context.workspace import Workspace

AGENTS_FILE = "AGENTS.md"


@dataclass(slots=True)
class ProjectMemoryInitResult:
    path: Path
    content: str
    created: bool
    overwritten: bool = False


class ProjectMemory:
    """Repo-scoped AGENTS.md project instructions."""

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path

    @property
    def agents_path(self) -> Path:
        return self.workspace_path / AGENTS_FILE

    def read_agents(self) -> str | None:
        if not self.agents_path.exists():
            return None
        return self.agents_path.read_text(encoding="utf-8")

    def init_agents(
        self,
        *,
        workspace: Workspace | None = None,
        overwrite: bool = False,
    ) -> ProjectMemoryInitResult:
        workspace = workspace or Workspace.discover(self.workspace_path)
        content = build_agents_content(workspace)
        existing = self.agents_path.exists()
        if existing and not overwrite:
            return ProjectMemoryInitResult(
                path=self.agents_path,
                content=self.agents_path.read_text(encoding="utf-8"),
                created=False,
                overwritten=False,
            )
        self.agents_path.write_text(content, encoding="utf-8")
        return ProjectMemoryInitResult(
            path=self.agents_path,
            content=content,
            created=not existing,
            overwritten=existing,
        )


def build_agents_content(workspace: Workspace) -> str:
    languages = ", ".join(workspace.detected_languages) or "unknown"
    frameworks = ", ".join(workspace.detected_frameworks) or "unknown"
    tests = ", ".join(workspace.test_commands) or "not detected"
    package_manager = workspace.package_manager or "not detected"
    git = "yes" if workspace.is_git_repo else "no"
    branch = workspace.current_branch or "unknown"
    test_lines = _command_lines(workspace.test_commands)
    return f"""# AGENTS.md

## Project
- Root: {workspace.root_path}
- Git repo: {git}
- Git branch: {branch}
- Languages: {languages}
- Frameworks: {frameworks}
- Package manager: {package_manager}
- Tests: {tests}

## Agent Workflow
- Understand the root cause before changing code.
- Keep edits scoped to the requested task and existing project patterns.
- Prefer plan-first work for multi-file or risky changes.
- Do not read or print secrets from `.env`, keys, tokens, or credential files.
- Represent changes as reviewable patches and run the relevant verification command.

## Verification
{test_lines}

## Helmcode Notes
- Use `helmcode agents plan <task>` to inspect Coding Plan multi-agent model allocation before spending provider quota.
- Use `helmcode sessions`, `helmcode replay <session-id>`, and `helmcode stats` to inspect local audit history.
"""


def _command_lines(commands: list[str]) -> str:
    if not commands:
        return "- No test command detected yet. Add one after confirming the project workflow."
    return "\n".join(f"- `{command}`" for command in commands)
