from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel

from helmcode.tools.base import Tool, ToolResult


class GitInput(BaseModel):
    root_path: Path = Path.cwd()


class GitStatusTool(Tool):
    name = "git_status"
    description = "Show git status for the workspace."
    input_schema = GitInput

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, GitInput)
        return _git(params.root_path, ["status", "--short", "--branch"])


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Show current git diff for the workspace."
    input_schema = GitInput

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, GitInput)
        return _git(params.root_path, ["diff"])


def _git(root_path: Path, args: list[str]) -> ToolResult:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        return ToolResult(ok=False, content="git is not installed", data={})
    content = completed.stdout if completed.stdout else completed.stderr
    return ToolResult(ok=completed.returncode == 0, content=content, data={"returncode": completed.returncode})
