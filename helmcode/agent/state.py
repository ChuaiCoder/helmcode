from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class AgentPlan:
    content: str


@dataclass(slots=True)
class AgentState:
    session_id: str
    workspace_path: Path
    user_task: str
    created_at: datetime
    plan: AgentPlan | None = None
    pending_patch: str | None = None
    patches_applied: list[str] = field(default_factory=list)
    shell_commands_run: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    final_summary: str | None = None

    @classmethod
    def start(cls, workspace_path: Path, user_task: str) -> "AgentState":
        return cls(
            session_id=str(uuid.uuid4()),
            workspace_path=workspace_path,
            user_task=user_task,
            created_at=datetime.now(UTC),
        )
