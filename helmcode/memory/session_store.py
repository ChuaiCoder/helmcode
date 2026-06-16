from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from helmcode.core.constants import SESSION_DB_FILE, SESSION_DIR_NAME

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionEvent:
    session_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class SessionStore:
    def __init__(self, workspace_path: Path, enable_structured_logging: bool = True) -> None:
        self.workspace_path = workspace_path
        self.db_path = workspace_path / SESSION_DIR_NAME / SESSION_DB_FILE
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()
        self.enable_structured_logging = enable_structured_logging
        self.json_log_path = workspace_path / SESSION_DIR_NAME / "audit_log.jsonl"
        self._alert_callbacks: list[Any] = []

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

    def register_alert_callback(self, callback: Any) -> None:
        self._alert_callbacks.append(callback)

    def record(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        timestamp = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events(session_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    timestamp,
                ),
            )

        if self.enable_structured_logging:
            self._write_json_log(session_id, event_type, payload, timestamp)

        if self._should_alert(event_type):
            self._trigger_alert(session_id, event_type, payload)

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

    def _write_json_log(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        timestamp: str,
    ) -> None:
        log_entry = {
            "session_id": session_id,
            "event_type": event_type,
            "payload": payload,
            "timestamp": timestamp,
            "workspace": str(self.workspace_path),
        }
        try:
            with open(self.json_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to write JSON log: %s", e)

    def _should_alert(self, event_type: str) -> bool:
        alert_event_types = {"command_result", "error", "patch_applied", "command_denied"}
        return event_type in alert_event_types

    def _trigger_alert(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        alert_data = {
            "session_id": session_id,
            "event_type": event_type,
            "payload": payload,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        for callback in self._alert_callbacks:
            try:
                callback(alert_data)
            except Exception as e:
                logger.error("Alert callback failed: %s", e)
