from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME
from helmcode.patch.apply import apply_unified_patch
from helmcode.patch.parser import PatchParser
from helmcode.safety.risk import RiskLevel
from helmcode.tools.base import Tool, ToolResult


class WritePatchInput(BaseModel):
    root_path: Path
    patch: str


class WritePatchTool(Tool):
    name = "write_patch"
    description = "Validate and store a pending unified diff patch without applying it."
    input_schema = WritePatchInput
    risk_level = RiskLevel.MEDIUM

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, WritePatchInput)
        parsed = PatchParser().parse(params.patch)
        state_dir = params.root_path / SESSION_DIR_NAME
        state_dir.mkdir(exist_ok=True)
        patch_path = state_dir / PENDING_PATCH_FILE
        patch_path.write_text(params.patch, encoding="utf-8")
        return ToolResult(
            ok=True,
            content=params.patch,
            data={"files": parsed.files, "pending_patch_path": str(patch_path)},
        )


class ApplyPatchInput(BaseModel):
    root_path: Path
    patch: str
    confirmed: bool = False


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = "Apply a confirmed unified diff patch."
    input_schema = ApplyPatchInput
    risk_level = RiskLevel.HIGH

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, ApplyPatchInput)
        if not params.confirmed:
            return ToolResult(ok=False, content="Patch application requires confirmation", data={})
        result = apply_unified_patch(params.root_path, params.patch)
        return ToolResult(ok=True, content="Patch applied", data={"files": result.applied_files})
