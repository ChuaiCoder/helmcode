from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from helmcode.core.constants import SESSION_DIR_NAME
from helmcode.tools.shell import ShellTool

HOOKS_FILE_NAME = "hooks.json"
DEFAULT_HOOK_TIMEOUT_SECONDS = 30
HOOK_EVENTS = (
    "pre_plan",
    "post_plan",
    "pre_patch",
    "post_patch",
    "post_apply",
    "post_test",
)
HOOK_EVENT_DESCRIPTIONS = {
    "pre_plan": "before model allocation and planning provider calls",
    "post_plan": "after a plan has been generated and recorded",
    "pre_patch": "before patch generation starts",
    "post_patch": "after a patch has been generated and recorded",
    "post_apply": "after a patch has been applied",
    "post_test": "after each test command result, including repair attempts",
}


@dataclass(slots=True)
class Hook:
    id: str
    event: str
    command: str
    required: bool = False
    enabled: bool = True
    timeout_seconds: int = DEFAULT_HOOK_TIMEOUT_SECONDS
    description: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "event": self.event,
            "command": self.command,
            "required": self.required,
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "description": self.description,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class HookRunResult:
    hook: Hook
    ok: bool
    output: str
    data: dict[str, object]
    event_payload: dict[str, object]

    def to_event_payload(self) -> dict[str, object]:
        return {
            "hook_id": self.hook.id,
            "event": self.hook.event,
            "command": self.hook.command,
            "required": self.hook.required,
            "enabled": self.hook.enabled,
            "timeout_seconds": self.hook.timeout_seconds,
            "ok": self.ok,
            "output": self.output,
            "data": self.data,
            "event_payload": self.event_payload,
        }


class HookStore:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.path = workspace_path / SESSION_DIR_NAME / HOOKS_FILE_NAME

    def list(self) -> list[Hook]:
        payload = self._read()
        hooks = payload.get("hooks")
        if not isinstance(hooks, list):
            return []
        result: list[Hook] = []
        for item in hooks:
            if not isinstance(item, dict):
                continue
            try:
                result.append(_hook_from_dict(item))
            except ValueError:
                continue
        return result

    def matching(self, event: str) -> list[Hook]:
        _validate_event(event)
        return [hook for hook in self.list() if hook.event == event and hook.enabled]

    def get(self, hook_id: str) -> Hook:
        for hook in self.list():
            if hook.id == hook_id:
                return hook
        raise KeyError(hook_id)

    def add(
        self,
        *,
        event: str,
        command: str,
        hook_id: str | None = None,
        required: bool = False,
        enabled: bool = True,
        timeout_seconds: int = DEFAULT_HOOK_TIMEOUT_SECONDS,
        description: str = "",
    ) -> Hook:
        _validate_event(event)
        normalized_command = " ".join(command.strip().split())
        if not normalized_command:
            raise ValueError("hook command cannot be empty")
        timeout_seconds = _validate_timeout_seconds(timeout_seconds)
        normalized_description = description.strip()
        hooks = self.list()
        selected_id = _dedupe_id(
            _normalize_id(hook_id or f"{event}-{_slug(normalized_command)}"),
            {hook.id for hook in hooks},
        )
        hook = Hook(
            id=selected_id,
            event=event,
            command=normalized_command,
            required=required,
            enabled=enabled,
            timeout_seconds=timeout_seconds,
            description=normalized_description,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._write([*hooks, hook])
        return hook

    def remove(self, hook_id: str) -> bool:
        hooks = self.list()
        kept = [hook for hook in hooks if hook.id != hook_id]
        if len(kept) == len(hooks):
            return False
        self._write(kept)
        return True

    def set_enabled(self, hook_id: str, enabled: bool) -> bool:
        hooks = self.list()
        changed = False
        for hook in hooks:
            if hook.id == hook_id:
                hook.enabled = enabled
                changed = True
        if changed:
            self._write(hooks)
        return changed

    def set_required(self, hook_id: str, required: bool) -> bool:
        hooks = self.list()
        changed = False
        for hook in hooks:
            if hook.id == hook_id:
                hook.required = required
                changed = True
        if changed:
            self._write(hooks)
        return changed

    def clear(self) -> int:
        hooks = self.list()
        self._write([])
        return len(hooks)

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, hooks: list[Hook]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "hooks": [hook.to_dict() for hook in hooks],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class HookRunner:
    def __init__(
        self,
        workspace_path: Path,
        *,
        permission_mode: str,
        shell_tool: ShellTool | None = None,
    ) -> None:
        self.workspace_path = workspace_path
        self.permission_mode = permission_mode
        self.shell_tool = shell_tool or ShellTool()

    def run_event(
        self,
        event: str,
        *,
        session_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> list[HookRunResult]:
        _validate_event(event)
        results: list[HookRunResult] = []
        for hook in HookStore(self.workspace_path).matching(event):
            event_payload = _build_event_payload(
                hook=hook,
                workspace_path=self.workspace_path,
                session_id=session_id,
                payload=payload or {},
            )
            result = self.shell_tool.run(
                {
                    "root_path": self.workspace_path,
                    "permission_mode": self.permission_mode,
                    "command": hook.command,
                    "timeout_seconds": hook.timeout_seconds,
                    "stdin": json.dumps(event_payload, ensure_ascii=False),
                }
            )
            hook_result = HookRunResult(
                hook=hook,
                ok=result.ok,
                output=result.content,
                data=result.data,
                event_payload=event_payload,
            )
            results.append(hook_result)
        return results


def _hook_from_dict(payload: dict[str, object]) -> Hook:
    hook_id = payload.get("id")
    event = payload.get("event")
    command = payload.get("command")
    if not isinstance(hook_id, str) or not isinstance(event, str) or not isinstance(command, str):
        raise ValueError("invalid hook")
    _validate_event(event)
    return Hook(
        id=hook_id,
        event=event,
        command=command,
        required=bool(payload.get("required", False)),
        enabled=bool(payload.get("enabled", True)),
        timeout_seconds=_validate_timeout_seconds(
            payload.get("timeout_seconds", DEFAULT_HOOK_TIMEOUT_SECONDS)
        ),
        description=str(payload.get("description") or ""),
        created_at=str(payload.get("created_at") or ""),
    )


def _validate_event(event: str) -> None:
    if event not in HOOK_EVENTS:
        raise ValueError(f"hook event must be one of: {', '.join(sorted(HOOK_EVENTS))}")


def _validate_timeout_seconds(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("hook timeout must be an integer number of seconds")
    try:
        timeout_seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("hook timeout must be an integer number of seconds") from exc
    if timeout_seconds < 1 or timeout_seconds > 600:
        raise ValueError("hook timeout must be between 1 and 600 seconds")
    return timeout_seconds


def _normalize_id(value: str) -> str:
    hook_id = "-".join(re.findall(r"[A-Za-z0-9]+", value.lower()))
    if not hook_id:
        raise ValueError("hook id must contain letters or numbers")
    return hook_id


def _slug(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value.lower())
    return "-".join(words[:6]) or "hook"


def _dedupe_id(hook_id: str, existing_ids: set[str]) -> str:
    if hook_id not in existing_ids:
        return hook_id
    index = 2
    while f"{hook_id}-{index}" in existing_ids:
        index += 1
    return f"{hook_id}-{index}"


def _build_event_payload(
    *,
    hook: Hook,
    workspace_path: Path,
    session_id: str | None,
    payload: dict[str, Any],
) -> dict[str, object]:
    return {
        "version": 1,
        "event": hook.event,
        "hook_id": hook.id,
        "required": hook.required,
        "workspace": str(workspace_path),
        "session_id": session_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
