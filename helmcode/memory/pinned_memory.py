from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from helmcode.core.constants import SESSION_DIR_NAME

MEMORY_FILE_NAME = "memory.json"

SECRET_TEXT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(api[_-]?key|secret|token|password|private[_-]?key)\s*=",
        r"\bsk-[A-Za-z0-9_-]{12,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ]
]


@dataclass(slots=True)
class MemoryEntry:
    id: str
    text: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "created_at": self.created_at,
        }


class PinnedMemoryStore:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.path = workspace_path / SESSION_DIR_NAME / MEMORY_FILE_NAME

    def list(self) -> list[MemoryEntry]:
        payload = self._read()
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return []
        result: list[MemoryEntry] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            entry_id = item.get("id")
            text = item.get("text")
            created_at = item.get("created_at")
            if isinstance(entry_id, str) and isinstance(text, str) and isinstance(created_at, str):
                result.append(MemoryEntry(id=entry_id, text=text, created_at=created_at))
        return result

    def get(self, entry_id: str) -> MemoryEntry:
        for entry in self.list():
            if entry.id == entry_id:
                return entry
        raise KeyError(entry_id)

    def add(self, text: str, *, entry_id: str | None = None) -> MemoryEntry:
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("memory text cannot be empty")
        _raise_if_secret_like(normalized_text)
        entries = self.list()
        existing_ids = {entry.id for entry in entries}
        selected_id = _normalize_id(entry_id) if entry_id else _slug(normalized_text)
        selected_id = _dedupe_id(selected_id, existing_ids)
        entry = MemoryEntry(
            id=selected_id,
            text=normalized_text,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._write([*entries, entry])
        return entry

    def delete(self, entry_id: str) -> bool:
        entries = self.list()
        kept = [entry for entry in entries if entry.id != entry_id]
        if len(kept) == len(entries):
            return False
        self._write(kept)
        return True

    def clear(self) -> int:
        entries = self.list()
        self._write([])
        return len(entries)

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, entries: list[MemoryEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "entries": [entry.to_dict() for entry in entries],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_pinned_memory_for_context(entries: list[MemoryEntry], *, limit: int = 20) -> str:
    selected = entries[:limit]
    if not selected:
        return ""
    return "\n".join(f"- [{entry.id}] {entry.text}" for entry in selected)


def _raise_if_secret_like(text: str) -> None:
    for pattern in SECRET_TEXT_PATTERNS:
        if pattern.search(text):
            raise ValueError(f"memory text looks sensitive: {pattern.pattern}")


def _slug(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    slug = "-".join(words[:6])
    return slug or "memory"


def _normalize_id(entry_id: str | None) -> str:
    if entry_id is None:
        return "memory"
    slug = "-".join(re.findall(r"[A-Za-z0-9]+", entry_id.lower()))
    if not slug:
        raise ValueError("memory id must contain letters or numbers")
    return slug


def _dedupe_id(entry_id: str, existing_ids: set[str]) -> str:
    if entry_id not in existing_ids:
        return entry_id
    index = 2
    while f"{entry_id}-{index}" in existing_ids:
        index += 1
    return f"{entry_id}-{index}"
