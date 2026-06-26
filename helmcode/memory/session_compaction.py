from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from helmcode.core.constants import SESSION_DIR_NAME
from helmcode.memory.session_store import SessionEvent, SessionStore

COMPACTIONS_DIR = "compactions"
COMPACTIONS_INDEX = "compactions.json"
MAX_TEXT_CHARS = 2_000


@dataclass(slots=True)
class SessionCompaction:
    session_id: str
    path: Path
    created_at: datetime
    event_count: int
    source_chars: int
    compacted_chars: int
    task: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "path": str(self.path),
            "created_at": self.created_at.isoformat(),
            "event_count": self.event_count,
            "source_chars": self.source_chars,
            "compacted_chars": self.compacted_chars,
            "task": self.task,
        }


class SessionCompactionStore:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.root_path = workspace_path / SESSION_DIR_NAME / COMPACTIONS_DIR
        self.index_path = self.root_path / COMPACTIONS_INDEX

    def compact(self, session_id: str) -> SessionCompaction:
        store = SessionStore(self.workspace_path)
        events = [
            event
            for event in store.list_events(session_id)
            if event.event_type != "session_compacted"
        ]
        if not events:
            raise ValueError(f"no events found for session: {session_id}")
        source_chars = sum(
            len(json.dumps(event.to_dict(), ensure_ascii=False, default=str))
            for event in events
        )
        created_at = datetime.now(UTC)
        task = _first_task(events)
        content = _render_compaction(
            session_id=session_id,
            events=events,
            created_at=created_at,
            source_chars=source_chars,
        )
        path = self.root_path / f"{_safe_filename(session_id)}.md"
        self.root_path.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        compaction = SessionCompaction(
            session_id=session_id,
            path=path,
            created_at=created_at,
            event_count=len(events),
            source_chars=source_chars,
            compacted_chars=len(content),
            task=task,
        )
        self._upsert(compaction)
        store.record(
            session_id,
            "session_compacted",
            {
                "path": str(path),
                "event_count": compaction.event_count,
                "source_chars": compaction.source_chars,
                "compacted_chars": compaction.compacted_chars,
            },
        )
        return compaction

    def list(self, limit: int = 20) -> list[SessionCompaction]:
        compactions = self._load()
        compactions.sort(key=lambda item: item.created_at, reverse=True)
        return compactions[:limit]

    def read_text(self, session_id: str) -> str:
        path = self.root_path / f"{_safe_filename(session_id)}.md"
        if not path.exists():
            raise ValueError(f"no compaction found for session: {session_id}")
        return path.read_text(encoding="utf-8")

    def _upsert(self, compaction: SessionCompaction) -> None:
        compactions = [
            existing
            for existing in self._load()
            if existing.session_id != compaction.session_id
        ]
        compactions.append(compaction)
        compactions.sort(key=lambda item: item.created_at, reverse=True)
        payload = {"compactions": [item.to_dict() for item in compactions]}
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> list[SessionCompaction]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_compactions = payload.get("compactions") if isinstance(payload, dict) else None
        if not isinstance(raw_compactions, list):
            return []
        compactions: list[SessionCompaction] = []
        for item in raw_compactions:
            if not isinstance(item, dict):
                continue
            try:
                compactions.append(
                    SessionCompaction(
                        session_id=str(item["session_id"]),
                        path=Path(str(item["path"])),
                        created_at=datetime.fromisoformat(str(item["created_at"])),
                        event_count=_as_int(item.get("event_count")),
                        source_chars=_as_int(item.get("source_chars")),
                        compacted_chars=_as_int(item.get("compacted_chars")),
                        task=str(item["task"]) if item.get("task") is not None else None,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return compactions


def _render_compaction(
    *,
    session_id: str,
    events: list[SessionEvent],
    created_at: datetime,
    source_chars: int,
) -> str:
    task = _first_task(events) or "unknown"
    sections = [
        "# Helmcode Session Compaction",
        "",
        f"- Session: {session_id}",
        f"- Created: {created_at.isoformat()}",
        f"- Events compacted: {len(events)}",
        f"- Source chars: {source_chars}",
        f"- Task: {_one_line(task)}",
        "",
        "## Coding Plan",
        _coding_plan_section(events),
        "",
        "## Plans",
        _payload_text_section(events, "plan_created", "content"),
        "",
        "## Model Calls",
        _model_calls_section(events),
        "",
        "## Patches",
        _patches_section(events),
        "",
        "## Commands And Tests",
        _command_section(events),
        "",
        "## Errors",
        _payload_text_section(events, "error", "message"),
        "",
        "## Timeline",
        _timeline_section(events),
        "",
    ]
    return "\n".join(sections)


def _coding_plan_section(events: list[SessionEvent]) -> str:
    allocations = [event.payload for event in events if event.event_type == "task_allocated"]
    if not allocations:
        return "- No Coding Plan allocation recorded."
    lines: list[str] = []
    for allocation in allocations:
        lines.extend(
            [
                f"- Task type: {allocation.get('detected_task_type', 'unknown')}",
                f"- Complexity: {allocation.get('complexity', 'unknown')}",
                f"- Strategy: {allocation.get('strategy', 'unknown')}",
                (
                    "- Cost: "
                    f"selected {allocation.get('selected_cost_score', 0)} / "
                    f"baseline {allocation.get('baseline_cost_score', 0)} / "
                    f"save {allocation.get('estimated_savings_score', 0)}"
                ),
            ]
        )
        max_cost = allocation.get("max_cost_score")
        if max_cost is not None:
            lines.append(f"- Budget: max {max_cost}, exceeded={allocation.get('budget_exceeded')}")
        assignments = allocation.get("assignments")
        if isinstance(assignments, list) and assignments:
            lines.append("- Route:")
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    continue
                required = "required" if assignment.get("required") else "optional"
                lines.append(
                    "  - "
                    f"{assignment.get('agent_id', 'unknown')} "
                    f"({assignment.get('task_type', 'unknown')}, {required}) -> "
                    f"{assignment.get('model_id', 'unknown')} "
                    f"cost={assignment.get('estimated_cost_score', 0)}"
                )
        warnings = allocation.get("warnings")
        if isinstance(warnings, list) and warnings:
            lines.append("- Warnings:")
            lines.extend(f"  - {_one_line(str(warning))}" for warning in warnings)
    return "\n".join(lines)


def _payload_text_section(events: list[SessionEvent], event_type: str, key: str) -> str:
    values = [
        str(event.payload.get(key))
        for event in events
        if event.event_type == event_type and event.payload.get(key) is not None
    ]
    if not values:
        return f"- No {event_type} events recorded."
    return "\n\n".join(f"```text\n{_clip(value, MAX_TEXT_CHARS)}\n```" for value in values)


def _model_calls_section(events: list[SessionEvent]) -> str:
    calls = [event.payload for event in events if event.event_type == "model_called"]
    if not calls:
        return "- No model calls recorded."
    lines = []
    for call in calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else {}
        total_tokens = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
        cached_tokens = usage.get("cached_tokens", 0) if isinstance(usage, dict) else 0
        lines.append(
            "- "
            f"{call.get('role', 'unknown')}/{call.get('task_type', 'unknown')} -> "
            f"{call.get('model_id', 'unknown')} "
            f"routing={call.get('routing_mode', 'unknown')} "
            f"tokens={total_tokens} cached={cached_tokens}"
        )
    return "\n".join(lines)


def _patches_section(events: list[SessionEvent]) -> str:
    patches = [
        event
        for event in events
        if event.event_type in {"patch_created", "patch_applied", "patch_reviewed"}
    ]
    if not patches:
        return "- No patch events recorded."
    lines = []
    for event in patches:
        payload = event.payload
        files = payload.get("files")
        file_text = ", ".join(str(item) for item in files) if isinstance(files, list) else "none"
        repair = payload.get("repair_attempt")
        suffix = f" repair={repair}" if repair is not None else ""
        if event.event_type == "patch_reviewed":
            lines.append(f"- patch_reviewed: {_one_line(str(payload.get('content', '')))}")
        else:
            lines.append(f"- {event.event_type}:{suffix} files={file_text}")
    return "\n".join(lines)


def _command_section(events: list[SessionEvent]) -> str:
    commands = [event.payload for event in events if event.event_type == "command_result"]
    if not commands:
        return "- No command results recorded."
    lines = []
    for command in commands:
        lines.append(
            "- "
            f"{command.get('command', 'unknown')} ok={command.get('ok')} "
            f"output={_one_line(_clip(str(command.get('output', '')), 300))}"
        )
    return "\n".join(lines)


def _timeline_section(events: list[SessionEvent]) -> str:
    return "\n".join(
        f"- {event.created_at.isoformat()} {event.event_type}"
        for event in events
    )


def _first_task(events: list[SessionEvent]) -> str | None:
    for event in events:
        if event.event_type == "user_message":
            content = event.payload.get("content")
            if isinstance(content, str):
                return content
    return None


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return safe or "session"


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
