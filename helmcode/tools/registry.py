from __future__ import annotations

from helmcode.tools.base import Tool
from helmcode.tools.diagnostics import DiagnosticsTool
from helmcode.tools.git import GitDiffTool, GitStatusTool
from helmcode.tools.list_files import ListFilesTool
from helmcode.tools.read_file import ReadFileTool
from helmcode.tools.search_code import SearchCodeTool
from helmcode.tools.shell import ShellTool
from helmcode.tools.tests import RunTestsTool
from helmcode.tools.write_patch import WritePatchTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[Tool]:
        return [self._tools[name] for name in self.names()]


def default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    shell_tool = ShellTool()
    for tool in [
        DiagnosticsTool(),
        GitDiffTool(),
        GitStatusTool(),
        ListFilesTool(),
        ReadFileTool(),
        SearchCodeTool(),
        shell_tool,
        RunTestsTool(shell_tool=shell_tool),
        WritePatchTool(),
    ]:
        registry.register(tool)
    return registry
