from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from helmcode.core.constants import SESSION_DIR_NAME

PREPLAN_CACHE_FILE = "preplan_cache.json"


@dataclass(slots=True)
class PreplanCacheEntry:
    key: str
    agent_id: str
    task_type: str
    model_id: str
    content: str
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "agent_id": self.agent_id,
            "task_type": self.task_type,
            "model_id": self.model_id,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "PreplanCacheEntry":
        return cls(
            key=str(payload["key"]),
            agent_id=str(payload["agent_id"]),
            task_type=str(payload["task_type"]),
            model_id=str(payload["model_id"]),
            content=str(payload["content"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )


class PreplanCache:
    def __init__(self, workspace_path: Path, max_entries: int = 200) -> None:
        self.workspace_path = workspace_path
        self.path = workspace_path / SESSION_DIR_NAME / PREPLAN_CACHE_FILE
        self.max_entries = max_entries

    def key_for(
        self,
        *,
        agent_id: str,
        task_type: str,
        model_id: str,
        task: str,
        base_context: str,
        previous_outputs: list[str],
    ) -> str:
        payload = {
            "agent_id": agent_id,
            "task_type": task_type,
            "model_id": model_id,
            "task": task,
            "base_context": base_context,
            "previous_outputs": previous_outputs,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> PreplanCacheEntry | None:
        entries = self._load()
        return entries.get(key)

    def put(
        self,
        *,
        key: str,
        agent_id: str,
        task_type: str,
        model_id: str,
        content: str,
    ) -> PreplanCacheEntry:
        entries = self._load()
        entry = PreplanCacheEntry(
            key=key,
            agent_id=agent_id,
            task_type=task_type,
            model_id=model_id,
            content=content,
            created_at=datetime.now(UTC),
        )
        entries[key] = entry
        self._save(entries)
        return entry

    def _load(self) -> dict[str, PreplanCacheEntry]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        raw_entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(raw_entries, dict):
            return {}
        entries: dict[str, PreplanCacheEntry] = {}
        for key, value in raw_entries.items():
            if not isinstance(value, dict):
                continue
            try:
                entry = PreplanCacheEntry.from_dict(value)
            except (KeyError, TypeError, ValueError):
                continue
            entries[str(key)] = entry
        return entries

    def _save(self, entries: dict[str, PreplanCacheEntry]) -> None:
        kept_entries = _latest_entries(entries, self.max_entries)
        payload: dict[str, Any] = {
            "entries": {key: entry.to_dict() for key, entry in kept_entries.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _latest_entries(entries: dict[str, PreplanCacheEntry], limit: int) -> dict[str, PreplanCacheEntry]:
    ordered = sorted(entries.items(), key=lambda item: item[1].created_at, reverse=True)
    return dict(ordered[:limit])
