from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AgentSessionEvent:
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(slots=True)
class AgentSession:
    session_id: str
    workspace_path: Path
    user_task: str
    created_at: datetime
    events: list[AgentSessionEvent] = field(default_factory=list)

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append(
            AgentSessionEvent(
                event_type=event_type,
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )
