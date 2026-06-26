from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from helmcode.patch.parser import PatchParser
from helmcode.memory.session_store import SessionStore
from helmcode.tools.base import ToolResult
from helmcode.tools.hooked import raise_if_hook_blocked, run_tool_with_lifecycle_hooks
from helmcode.tools.shell import ShellTool
from helmcode.tools.tests import RunTestsTool
from helmcode.tools.write_patch import ApplyPatchTool, WritePatchTool


@dataclass(slots=True)
class TestRunResult:
    ok: bool
    output: str


class Executor:
    def __init__(
        self,
        root_path: Path,
        permission_mode: str = "suggest",
        write_patch_tool: Any | None = None,
        apply_patch_tool: Any | None = None,
        shell_tool: Any | None = None,
        tests_tool: Any | None = None,
        session_store: SessionStore | None = None,
        session_id: str = "agent-executor",
    ) -> None:
        self.root_path = root_path
        self.permission_mode = permission_mode
        self.write_patch_tool = write_patch_tool or WritePatchTool()
        self.apply_patch_tool = apply_patch_tool or ApplyPatchTool()
        self.shell_tool = shell_tool or ShellTool()
        self.tests_tool = tests_tool or RunTestsTool(self.shell_tool)
        self.session_store = session_store
        self.session_id = session_id

    def prepare_patch(self, patch: str) -> list[str]:
        result = self._run_tool(
            self.write_patch_tool,
            {"root_path": self.root_path, "patch": patch},
        )
        if not result.ok:
            raise_if_hook_blocked(result)
            raise RuntimeError(result.content)
        parsed = PatchParser().parse(patch)
        return parsed.files

    def apply_patch(self, patch: str, confirmed: bool) -> list[str]:
        result = self._run_tool(
            self.apply_patch_tool,
            {"root_path": self.root_path, "patch": patch, "confirmed": confirmed}
        )
        if not result.ok:
            raise_if_hook_blocked(result)
            raise RuntimeError(result.content)
        files = result.data.get("files", [])
        return [str(file) for file in files]

    def run_tests(self, command: str | None = None) -> TestRunResult:
        result = self._run_tool(
            self.tests_tool,
            {
                "root_path": self.root_path,
                "permission_mode": self.permission_mode,
                "command": command,
            }
        )
        raise_if_hook_blocked(result)
        return TestRunResult(ok=result.ok, output=result.content)

    def _run_tool(self, tool: Any, raw_input: dict[str, Any]) -> ToolResult:
        return run_tool_with_lifecycle_hooks(
            tool,
            raw_input,
            workspace_path=self.root_path,
            permission_mode=self.permission_mode,
            session_store=self.session_store,
            session_id=self.session_id,
        )
