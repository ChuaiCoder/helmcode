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

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(slots=True)
class SessionSummary:
    session_id: str
    started_at: datetime
    updated_at: datetime
    event_count: int
    task: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "event_count": self.event_count,
            "task": self.task,
        }


@dataclass(slots=True)
class SessionStats:
    session_count: int
    event_count: int
    event_counts: dict[str, int]
    model_call_count: int
    patch_created_count: int
    patch_applied_count: int
    command_result_count: int
    first_event_at: datetime | None
    last_event_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_count": self.session_count,
            "event_count": self.event_count,
            "event_counts": self.event_counts,
            "model_call_count": self.model_call_count,
            "patch_created_count": self.patch_created_count,
            "patch_applied_count": self.patch_applied_count,
            "command_result_count": self.command_result_count,
            "first_event_at": self.first_event_at.isoformat() if self.first_event_at else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
        }


class SessionStore:
    def __init__(self, workspace_path: Path, enable_structured_logging: bool = True) -> None:
        self.workspace_path = workspace_path
        self.db_path = workspace_path / SESSION_DIR_NAME / SESSION_DB_FILE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT session_id, MIN(created_at), MAX(created_at), COUNT(*)
                FROM events
                GROUP BY session_id
                ORDER BY MAX(created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            task_rows = conn.execute(
                """
                SELECT session_id, payload
                FROM events
                WHERE event_type = 'user_message'
                ORDER BY id
                """
            ).fetchall()
        tasks: dict[str, str] = {}
        for session_id, payload_text in task_rows:
            if session_id in tasks:
                continue
            payload = _load_payload(payload_text)
            content = payload.get("content")
            if isinstance(content, str):
                tasks[session_id] = content
        return [
            SessionSummary(
                session_id=row[0],
                started_at=datetime.fromisoformat(row[1]),
                updated_at=datetime.fromisoformat(row[2]),
                event_count=int(row[3]),
                task=tasks.get(row[0]),
            )
            for row in rows
        ]

    def list_recent_events(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[SessionEvent]:
        if session_id:
            query = """
                SELECT session_id, event_type, payload, created_at
                FROM events
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            """
            params: tuple[object, ...] = (session_id, limit)
        else:
            query = """
                SELECT session_id, event_type, payload, created_at
                FROM events
                ORDER BY id DESC
                LIMIT ?
            """
            params = (limit,)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            SessionEvent(
                session_id=row[0],
                event_type=row[1],
                payload=_load_payload(row[2]),
                created_at=datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]

    def stats(self) -> SessionStats:
        with sqlite3.connect(self.db_path) as conn:
            session_count = conn.execute("SELECT COUNT(DISTINCT session_id) FROM events").fetchone()[0]
            rows = conn.execute(
                """
                SELECT event_type, COUNT(*)
                FROM events
                GROUP BY event_type
                ORDER BY event_type
                """
            ).fetchall()
            bounds = conn.execute("SELECT MIN(created_at), MAX(created_at), COUNT(*) FROM events").fetchone()
        event_counts = {event_type: int(count) for event_type, count in rows}
        first_event_at = datetime.fromisoformat(bounds[0]) if bounds and bounds[0] else None
        last_event_at = datetime.fromisoformat(bounds[1]) if bounds and bounds[1] else None
        event_count = int(bounds[2]) if bounds else 0
        return SessionStats(
            session_count=int(session_count or 0),
            event_count=event_count,
            event_counts=event_counts,
            model_call_count=event_counts.get("model_called", 0),
            patch_created_count=event_counts.get("patch_created", 0),
            patch_applied_count=event_counts.get("patch_applied", 0),
            command_result_count=event_counts.get("command_result", 0),
            first_event_at=first_event_at,
            last_event_at=last_event_at,
        )

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


def _load_payload(payload_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
