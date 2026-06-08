from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel

from helmcode.tools.base import Tool, ToolResult


class SearchCodeInput(BaseModel):
    query: str
    root_path: Path = Path.cwd()
    glob: str | None = None
    max_results: int = 100


class SearchCodeTool(Tool):
    name = "search_code"
    description = "Search code with ripgrep and return file, line, and snippet matches."
    input_schema = SearchCodeInput

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, SearchCodeInput)
        command = ["rg", "--line-number", "--no-heading", params.query]
        if params.glob:
            command.extend(["--glob", params.glob])
        try:
            completed = subprocess.run(
                command,
                cwd=params.root_path,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except FileNotFoundError:
            return ToolResult(ok=False, content="ripgrep (rg) is not installed", data={})

        lines = completed.stdout.splitlines()[: params.max_results]
        return ToolResult(
            ok=completed.returncode in {0, 1},
            content="\n".join(lines),
            data={"matches": lines, "returncode": completed.returncode},
        )
