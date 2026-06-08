from __future__ import annotations

from pathlib import Path

from helmcode.patch.parser import PatchParser
from helmcode.tools.shell import ShellTool
from helmcode.tools.tests import RunTestsTool
from helmcode.tools.write_patch import ApplyPatchTool, WritePatchTool


class Executor:
    def __init__(self, root_path: Path, permission_mode: str = "suggest") -> None:
        self.root_path = root_path
        self.permission_mode = permission_mode
        self.write_patch_tool = WritePatchTool()
        self.apply_patch_tool = ApplyPatchTool()
        self.shell_tool = ShellTool()
        self.tests_tool = RunTestsTool(self.shell_tool)

    def prepare_patch(self, patch: str) -> list[str]:
        parsed = PatchParser().parse(patch)
        self.write_patch_tool.run({"root_path": self.root_path, "patch": patch})
        return parsed.files

    def apply_patch(self, patch: str, confirmed: bool) -> list[str]:
        result = self.apply_patch_tool.run(
            {"root_path": self.root_path, "patch": patch, "confirmed": confirmed}
        )
        if not result.ok:
            raise RuntimeError(result.content)
        files = result.data.get("files", [])
        return [str(file) for file in files]

    def run_tests(self, command: str | None = None) -> str:
        result = self.tests_tool.run(
            {
                "root_path": self.root_path,
                "permission_mode": self.permission_mode,
                "command": command,
            }
        )
        return result.content
