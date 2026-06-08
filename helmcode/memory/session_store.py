from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from helmcode.core.constants import SESSION_DB_FILE, SESSION_DIR_NAME


@dataclass(slots=True)
class SessionEvent:
    session_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class SessionStore:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.db_path = workspace_path / SESSION_DIR_NAME / SESSION_DB_FILE
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def record(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events(session_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def list_events(self, session_id: str) -> list[SessionEvent]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT session_id, event_type, payload, created_at FROM events WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [
            SessionEvent(
                session_id=row[0],
                event_type=row[1],
                payload=json.loads(row[2]),
                created_at=datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]
