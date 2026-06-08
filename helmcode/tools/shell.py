from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel

from helmcode.safety.command_policy import CommandPolicy
from helmcode.safety.risk import RiskLevel
from helmcode.tools.base import Tool, ToolResult


class ShellInput(BaseModel):
    command: str
    root_path: Path = Path.cwd()
    permission_mode: str = "suggest"
    timeout_seconds: int = 120


class ShellTool(Tool):
    name = "shell"
    description = "Run a shell command after command policy validation."
    input_schema = ShellInput
    risk_level = RiskLevel.MEDIUM

    def __init__(self, policy: CommandPolicy | None = None) -> None:
        self.policy = policy or CommandPolicy()

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, ShellInput)
        decision = self.policy.check(params.command, permission_mode=params.permission_mode)
        if not decision.allowed:
            return ToolResult(
                ok=False,
                content=decision.reason,
                data={
                    "risk": decision.risk.value,
                    "requires_confirmation": decision.requires_confirmation,
                },
            )
        completed = subprocess.run(
            params.command,
            cwd=params.root_path,
            shell=True,
            capture_output=True,
            text=True,
            timeout=params.timeout_seconds,
        )
        return ToolResult(
            ok=completed.returncode == 0,
            content=(completed.stdout + completed.stderr).strip(),
            data={"returncode": completed.returncode},
        )
