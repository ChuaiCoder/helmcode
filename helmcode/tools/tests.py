from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from helmcode.context.workspace import Workspace
from helmcode.tools.base import Tool, ToolResult
from helmcode.tools.shell import ShellTool


class RunTestsInput(BaseModel):
    root_path: Path = Path.cwd()
    permission_mode: str = "edit"
    command: str | None = None


class RunTestsTool(Tool):
    name = "run_tests"
    description = "Detect and run the project test command."
    input_schema = RunTestsInput

    def __init__(self, shell_tool: ShellTool | None = None) -> None:
        self.shell_tool = shell_tool or ShellTool()

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, RunTestsInput)
        command = params.command
        if command is None:
            workspace = Workspace.discover(params.root_path)
            command = workspace.test_commands[0] if workspace.test_commands else None
        if command is None:
            return ToolResult(ok=False, content="No test command detected", data={})
        return self.shell_tool.run(
            {
                "command": command,
                "root_path": params.root_path,
                "permission_mode": params.permission_mode,
            }
        )
