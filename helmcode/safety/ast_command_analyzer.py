from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum


class CommandNodeType(str, Enum):
    COMMAND = "command"
    ARGUMENT = "argument"
    PIPE = "pipe"
    REDIRECT = "redirect"
    SUBCOMMAND = "subcommand"


@dataclass
class CommandNode:
    type: CommandNodeType
    value: str
    children: list["CommandNode"] | None = None
    start: int = 0
    end: int = 0


@dataclass
class AnalysisResult:
    is_safe: bool
    risk_level: str
    reasons: list[str]
    structure: CommandNode | None = None


class ASTCommandAnalyzer:
    def __init__(self) -> None:
        self._dangerous_commands = {
            "rm", "sudo", "chmod", "chown", "dd", "mkfs", "drop", "truncate", "delete",
        }
        self._dangerous_subcommands = {
            "git": {"reset", "clean"},
            "docker": {"system"},
            "kubectl": {"delete"},
            "terraform": {"apply"},
        }
        self._dangerous_flags = {
            "rm": {"-rf", "-fr", "-r", "-f"},
        }
        self._dangerous_sequences = {
            "docker": [("system", "prune")],
        }
        self._safe_commands = {
            "pytest", "python", "python3", "rg", "ls", "dir", "npm", "pnpm",
            "yarn", "go", "cargo", "mvn", "gradle", "uv", "cat", "head", "tail",
            "grep", "find", "echo", "pwd", "whoami", "date",
        }

    def analyze(self, command: str) -> AnalysisResult:
        if not command.strip():
            return AnalysisResult(
                is_safe=False,
                risk_level="blocked",
                reasons=["empty command"],
            )

        try:
            structure = self._parse_command(command)
        except Exception as e:
            return AnalysisResult(
                is_safe=False,
                risk_level="blocked",
                reasons=[f"failed to parse command: {e}"],
            )

        reasons: list[str] = []
        risk_level = "low"

        if self._has_pipe_danger(structure):
            reasons.append("contains dangerous pipe pattern")
            risk_level = "high"

        if self._has_redirect_danger(structure):
            reasons.append("contains dangerous redirect pattern")
            risk_level = "high"

        if self._has_dangerous_command(structure):
            reasons.append("contains dangerous command")
            risk_level = "blocked"

        if self._has_dangerous_invocation(structure):
            reasons.append("contains dangerous command invocation")
            risk_level = "high"

        is_safe = risk_level in ("low", "medium")

        return AnalysisResult(
            is_safe=is_safe,
            risk_level=risk_level,
            reasons=reasons,
            structure=structure,
        )

    def _parse_command(self, command: str) -> CommandNode:
        tokens = shlex.split(command, posix=False)
        if not tokens:
            return CommandNode(type=CommandNodeType.COMMAND, value="")

        root = CommandNode(
            type=CommandNodeType.COMMAND,
            value=tokens[0],
            children=[],
            start=0,
            end=len(command),
        )

        i = 1
        while i < len(tokens):
            token = tokens[i]
            if token == "|":
                pipe_node = CommandNode(
                    type=CommandNodeType.PIPE,
                    value="|",
                    children=[root],
                )
                i += 1
                if i < len(tokens):
                    next_command = self._parse_command_from_tokens(tokens[i:])
                    pipe_node.children.append(next_command)
                root = pipe_node
            elif token in (">", ">>", "<"):
                redirect_node = CommandNode(
                    type=CommandNodeType.REDIRECT,
                    value=token,
                    children=[root],
                )
                i += 1
                if i < len(tokens):
                    redirect_node.children.append(
                        CommandNode(type=CommandNodeType.ARGUMENT, value=tokens[i])
                    )
                root = redirect_node
            else:
                arg_node = CommandNode(
                    type=CommandNodeType.ARGUMENT,
                    value=token,
                )
                if root.children is None:
                    root.children = []
                root.children.append(arg_node)
            i += 1

        return root

    def _parse_command_from_tokens(self, tokens: list[str]) -> CommandNode:
        if not tokens:
            return CommandNode(type=CommandNodeType.COMMAND, value="")

        root = CommandNode(
            type=CommandNodeType.COMMAND,
            value=tokens[0],
            children=[],
        )

        for token in tokens[1:]:
            if token == "|":
                break
            arg_node = CommandNode(
                type=CommandNodeType.ARGUMENT,
                value=token,
            )
            if root.children is None:
                root.children = []
            root.children.append(arg_node)

        return root

    def _has_pipe_danger(self, node: CommandNode) -> bool:
        if node.type == CommandNodeType.PIPE:
            if node.children and len(node.children) >= 2:
                right_child = node.children[1]
                if right_child.type == CommandNodeType.COMMAND:
                    if right_child.value in ("sh", "bash", "zsh"):
                        return True
        if node.children:
            for child in node.children:
                if self._has_pipe_danger(child):
                    return True
        return False

    def _has_redirect_danger(self, node: CommandNode) -> bool:
        if node.type == CommandNodeType.REDIRECT:
            if node.value in (">", ">>"):
                if node.children and len(node.children) >= 2:
                    target = node.children[1].value
                    if target.startswith("/etc/") or target.startswith("~"):
                        return True
        if node.children:
            for child in node.children:
                if self._has_redirect_danger(child):
                    return True
        return False

    def _has_dangerous_command(self, node: CommandNode) -> bool:
        if node.type == CommandNodeType.COMMAND:
            cmd = node.value.lower()
            if cmd in self._dangerous_commands:
                return True
        if node.children:
            for child in node.children:
                if self._has_dangerous_command(child):
                    return True
        return False

    def _has_dangerous_invocation(self, node: CommandNode) -> bool:
        if node.type == CommandNodeType.COMMAND:
            cmd = node.value.lower()
            arguments = [
                child.value.lower()
                for child in node.children or []
                if child.type == CommandNodeType.ARGUMENT
            ]
            if any(argument in self._dangerous_flags.get(cmd, set()) for argument in arguments):
                return True
            if any(argument in self._dangerous_subcommands.get(cmd, set()) for argument in arguments):
                return True
            for sequence in self._dangerous_sequences.get(cmd, []):
                if _contains_sequence(arguments, sequence):
                    return True
        if node.children:
            for child in node.children:
                if self._has_dangerous_invocation(child):
                    return True
        return False


def _contains_sequence(values: list[str], sequence: tuple[str, ...]) -> bool:
    if len(sequence) > len(values):
        return False
    return any(
        tuple(values[index : index + len(sequence)]) == sequence
        for index in range(0, len(values) - len(sequence) + 1)
    )
