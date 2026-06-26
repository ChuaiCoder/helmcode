from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from helmcode.context.file_index import FileIndex
from helmcode.context.workspace import Workspace
from helmcode.core.constants import SESSION_DIR_NAME
from helmcode.safety.secret_scanner import SecretScanner

CHECKPOINT_DIR = "checkpoints"
DEFAULT_MAX_FILES = 1000
DEFAULT_MAX_FILE_BYTES = 1_000_000


@dataclass(slots=True)
class CheckpointFile:
    path: str
    sha256: str
    size: int
    content_b64: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "content_b64": self.content_b64,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CheckpointFile":
        return cls(
            path=str(payload["path"]),
            sha256=str(payload["sha256"]),
            size=int(payload["size"]),
            content_b64=str(payload["content_b64"]),
        )


@dataclass(slots=True)
class Checkpoint:
    id: str
    label: str
    created_at: str
    workspace_path: str
    git_head: str | None
    git_branch: str | None
    files: dict[str, CheckpointFile]
    skipped: list[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.files.values())

    def metadata(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "created_at": self.created_at,
            "workspace_path": self.workspace_path,
            "git_head": self.git_head,
            "git_branch": self.git_branch,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "skipped": self.skipped,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.metadata(),
            "files": {path: item.to_dict() for path, item in self.files.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Checkpoint":
        files_payload = payload.get("files", {})
        if not isinstance(files_payload, dict):
            files_payload = {}
        return cls(
            id=str(payload["id"]),
            label=str(payload.get("label", "")),
            created_at=str(payload["created_at"]),
            workspace_path=str(payload.get("workspace_path", "")),
            git_head=str(payload["git_head"]) if payload.get("git_head") else None,
            git_branch=str(payload["git_branch"]) if payload.get("git_branch") else None,
            files={
                str(path): CheckpointFile.from_dict(file_payload)
                for path, file_payload in files_payload.items()
                if isinstance(file_payload, dict)
            },
            skipped=[str(item) for item in payload.get("skipped", []) if isinstance(item, str)],
        )


@dataclass(slots=True)
class RestoreResult:
    checkpoint_id: str
    restored_files: list[str]
    missing_files: list[str]
    dry_run: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "restored_files": self.restored_files,
            "missing_files": self.missing_files,
            "dry_run": self.dry_run,
        }


class CheckpointStore:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path.resolve()
        self.checkpoint_dir = self.workspace_path / SESSION_DIR_NAME / CHECKPOINT_DIR
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.secret_scanner = SecretScanner()

    def create(
        self,
        *,
        label: str = "",
        max_files: int = DEFAULT_MAX_FILES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> Checkpoint:
        workspace = Workspace.discover(self.workspace_path)
        files = FileIndex(workspace.root_path, workspace.ignored_patterns).list_files(
            limit=max_files,
            use_cache=False,
        )
        checkpoint_files: dict[str, CheckpointFile] = {}
        skipped: list[str] = []
        for relative_path in files:
            if self.secret_scanner.check_path(relative_path).sensitive:
                skipped.append(f"{relative_path}: sensitive path")
                continue
            path = (self.workspace_path / relative_path).resolve()
            if not path.is_relative_to(self.workspace_path) or not path.is_file():
                skipped.append(f"{relative_path}: not a regular workspace file")
                continue
            size = path.stat().st_size
            if size > max_file_bytes:
                skipped.append(f"{relative_path}: larger than {max_file_bytes} bytes")
                continue
            data = path.read_bytes()
            checkpoint_files[relative_path] = CheckpointFile(
                path=relative_path,
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
                content_b64=base64.b64encode(data).decode("ascii"),
            )
        checkpoint_id = _checkpoint_id(label)
        checkpoint = Checkpoint(
            id=checkpoint_id,
            label=label,
            created_at=datetime.now(UTC).isoformat(),
            workspace_path=str(self.workspace_path),
            git_head=_git_output(self.workspace_path, ["rev-parse", "HEAD"]),
            git_branch=workspace.current_branch,
            files=checkpoint_files,
            skipped=skipped,
        )
        self._path_for(checkpoint_id).write_text(
            json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return checkpoint

    def list(self) -> list[Checkpoint]:
        checkpoints: list[Checkpoint] = []
        for path in sorted(self.checkpoint_dir.glob("*.json"), reverse=True):
            try:
                checkpoints.append(self.load(path.stem))
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
        return sorted(checkpoints, key=lambda item: item.created_at, reverse=True)

    def load(self, checkpoint_id: str) -> Checkpoint:
        path = self._path_for(checkpoint_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"checkpoint must be a mapping: {checkpoint_id}")
        return Checkpoint.from_dict(payload)

    def delete(self, checkpoint_id: str) -> bool:
        path = self._path_for(checkpoint_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def restore(
        self,
        checkpoint_id: str,
        *,
        paths: list[str] | None = None,
        dry_run: bool = False,
    ) -> RestoreResult:
        checkpoint = self.load(checkpoint_id)
        requested = set(paths or checkpoint.files.keys())
        restored: list[str] = []
        missing: list[str] = []
        for relative_path in sorted(requested):
            snapshot = checkpoint.files.get(relative_path)
            if snapshot is None:
                missing.append(relative_path)
                continue
            target = (self.workspace_path / relative_path).resolve()
            if not target.is_relative_to(self.workspace_path):
                missing.append(relative_path)
                continue
            restored.append(relative_path)
            if dry_run:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(snapshot.content_b64.encode("ascii")))
        return RestoreResult(
            checkpoint_id=checkpoint_id,
            restored_files=restored,
            missing_files=missing,
            dry_run=dry_run,
        )

    def _path_for(self, checkpoint_id: str) -> Path:
        if not checkpoint_id or any(char in checkpoint_id for char in "\\/"):
            raise ValueError(f"invalid checkpoint id: {checkpoint_id!r}")
        return self.checkpoint_dir / f"{checkpoint_id}.json"


def _checkpoint_id(label: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    digest = hashlib.sha1(f"{timestamp}:{label}".encode("utf-8")).hexdigest()[:8]
    return f"{timestamp}-{digest}"


def _git_output(root_path: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() or None
