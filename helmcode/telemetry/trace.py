from __future__ import annotations

from pathlib import Path
from typing import Any

from helmcode.memory.session_store import SessionStore


class Trace:
    def __init__(self, workspace_path: Path, session_id: str) -> None:
        self.session_id = session_id
        self.store = SessionStore(workspace_path)

    def event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.store.record(self.session_id, event_type, payload)
