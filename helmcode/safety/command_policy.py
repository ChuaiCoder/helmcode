from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum

from helmcode.safety.ast_command_analyzer import ASTCommandAnalyzer


class CommandRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


@dataclass(slots=True)
class CommandPolicyResult:
    allowed: bool
    risk: CommandRisk
    requires_confirmation: bool
    reason: str


class CommandPolicy:
    """Conservative shell command policy for local agent actions."""

    BLOCK_PATTERNS = [
        r"\brm\s+-[^\n;|&]*r[^\n;|&]*f\b",
        r"\bsudo\b",
        r"\bchmod\s+-R\b",
        r"\bchown\s+-R\b",
        r"\bcurl\b.*\|\s*(sh|bash)\b",
        r"\bwget\b.*\|\s*(sh|bash)\b",
        r"\bdd\s+",
        r"\bmkfs(\.|\\s|$)",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\s+-[^\n;|&]*f",
        r"\bdocker\s+system\s+prune\b",
        r"\bkubectl\s+delete\b",
        r"\bterraform\s+apply\b",
        r"\b(drop|truncate)\s+(table|database)\b",
        r"\bdelete\s+from\b",
    ]
    CONFIRM_PATTERNS = [
        r"\bnpm\s+publish\b",
        r"\bpnpm\s+publish\b",
        r"\byarn\s+npm\s+publish\b",
        r"\bgit\s+push\b",
        r"\bpip\s+install\b",
        r"\buv\s+pip\s+install\b",
    ]
    SAFE_PREFIXES = {
        "pytest",
        "python",
        "python3",
        "git",
        "rg",
        "ls",
        "dir",
        "npm",
        "pnpm",
        "yarn",
        "go",
        "cargo",
        "mvn",
        "gradle",
        "uv",
    }

    def __init__(self, use_ast_analysis: bool = True) -> None:
        self.use_ast_analysis = use_ast_analysis
        self.ast_analyzer = ASTCommandAnalyzer() if use_ast_analysis else None

    def check(self, command: str, permission_mode: str = "suggest") -> CommandPolicyResult:
        normalized = command.strip()
        lowered = normalized.lower()
        if not normalized:
            return CommandPolicyResult(False, CommandRisk.BLOCKED, False, "empty command")

        for pattern in self.BLOCK_PATTERNS:
            match = re.search(pattern, lowered)
            if match:
                return CommandPolicyResult(
                    allowed=False,
                    risk=CommandRisk.BLOCKED,
                    requires_confirmation=False,
                    reason=f"blocked destructive command pattern: {match.group(0)}",
                )

        for pattern in self.CONFIRM_PATTERNS:
            match = re.search(pattern, lowered)
            if match:
                return CommandPolicyResult(
                    allowed=False,
                    risk=CommandRisk.HIGH,
                    requires_confirmation=True,
                    reason=f"command requires explicit confirmation: {match.group(0)}",
                )

        if self.use_ast_analysis and self.ast_analyzer:
            ast_result = self.ast_analyzer.analyze(command)
            if not ast_result.is_safe:
                risk = CommandRisk.BLOCKED if ast_result.risk_level == "blocked" else CommandRisk.HIGH
                return CommandPolicyResult(
                    allowed=False,
                    risk=risk,
                    requires_confirmation=True,
                    reason=f"AST analysis detected: {', '.join(ast_result.reasons)}",
                )

        if permission_mode == "read_only" and not self._is_read_only(normalized):
            return CommandPolicyResult(
                allowed=False,
                risk=CommandRisk.MEDIUM,
                requires_confirmation=True,
                reason="read_only mode blocks non-read commands",
            )

        return CommandPolicyResult(
            allowed=True,
            risk=CommandRisk.LOW,
            requires_confirmation=False,
            reason="allowed low-risk command",
        )

    def _is_read_only(self, command: str) -> bool:
        try:
            parts = shlex.split(command, posix=False)
        except ValueError:
            return False
        if not parts:
            return False
        head = parts[0].lower()
        if head not in self.SAFE_PREFIXES:
            return False
        if head == "git":
            return len(parts) > 1 and parts[1] in {"status", "diff", "log", "show", "branch", "rev-parse"}
        if head in {"npm", "pnpm", "yarn"}:
            return "test" in parts or "lint" in parts or "typecheck" in parts
        return head in {"pytest", "python", "python3", "rg", "ls", "dir", "go", "cargo", "mvn", "gradle", "uv"}
