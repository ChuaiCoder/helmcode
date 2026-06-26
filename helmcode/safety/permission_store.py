from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from helmcode.core.constants import SESSION_DIR_NAME

PERMISSIONS_FILE_NAME = "permissions.json"


@dataclass(slots=True)
class PermissionStore:
    path: Path
    allowed_commands: list[str] = field(default_factory=list)

    @classmethod
    def for_workspace(cls, workspace_path: Path) -> "PermissionStore":
        path = workspace_path / SESSION_DIR_NAME / PERMISSIONS_FILE_NAME
        store = cls(path=path)
        store.allowed_commands = store._read()
        return store

    def add(self, command_prefix: str) -> bool:
        normalized = _normalize(command_prefix)
        if not normalized:
            raise ValueError("permission command prefix cannot be empty")
        if normalized in self.allowed_commands:
            return False
        self.allowed_commands.append(normalized)
        self.allowed_commands.sort()
        self._write()
        return True

    def remove(self, command_prefix: str) -> bool:
        normalized = _normalize(command_prefix)
        if normalized not in self.allowed_commands:
            return False
        self.allowed_commands = [item for item in self.allowed_commands if item != normalized]
        self._write()
        return True

    def clear(self) -> int:
        removed = len(self.allowed_commands)
        self.allowed_commands = []
        self._write()
        return removed

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "allowed_commands": self.allowed_commands,
        }

    def _read(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        commands = payload.get("allowed_commands") if isinstance(payload, dict) else None
        if not isinstance(commands, list):
            return []
        return sorted(_normalize(str(command)) for command in commands if _normalize(str(command)))

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "allowed_commands": self.allowed_commands,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize(command_prefix: str) -> str:
    return " ".join(command_prefix.strip().split())
