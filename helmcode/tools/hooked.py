from __future__ import annotations

from pathlib import Path
from typing import Any

from helmcode.core.exceptions import PermissionDenied
from helmcode.memory.hooks import HookRunner
from helmcode.memory.session_store import SessionStore
from helmcode.tools.base import Tool, ToolResult


def run_tool_with_lifecycle_hooks(
    tool: Tool,
    raw_input: dict[str, Any],
    *,
    workspace_path: Path,
    permission_mode: str,
    session_store: SessionStore | None = None,
    session_id: str = "tool-cli",
) -> ToolResult:
    """Run a tool with Reasonix-style PreToolUse/PostToolUse hooks."""
    runner = HookRunner(workspace_path, permission_mode=permission_mode)
    tool_name = _tool_name(tool)
    risk_level = _tool_risk_level(tool)
    pre_payload = {
        "tool": tool_name,
        "risk_level": risk_level,
        "input": sanitize_tool_payload(raw_input),
    }
    blocker = _run_tool_hooks(
        runner=runner,
        session_store=session_store,
        session_id=session_id,
        event="PreToolUse",
        payload=pre_payload,
    )
    if blocker is not None:
        return blocker

    result = tool.run(raw_input)

    post_payload = {
        "tool": tool_name,
        "risk_level": risk_level,
        "input": sanitize_tool_payload(raw_input),
        "result": {
            "ok": result.ok,
            "content": _clip_text(result.content),
            "data": sanitize_tool_payload(result.data),
        },
    }
    blocker = _run_tool_hooks(
        runner=runner,
        session_store=session_store,
        session_id=session_id,
        event="PostToolUse",
        payload=post_payload,
    )
    if blocker is not None:
        return blocker
    return result


def sanitize_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if lowered in {"patch", "stdin"}:
            safe[key] = f"<redacted {lowered}>"
        elif isinstance(value, str) and len(value) > 500:
            safe[key] = value[:500] + "\n[truncated]"
        elif isinstance(value, dict):
            safe[key] = sanitize_tool_payload(value)
        elif isinstance(value, Path):
            safe[key] = str(value)
        elif isinstance(value, (list, tuple)):
            safe[key] = [_json_safe(item) for item in value]
        else:
            safe[key] = _json_safe(value)
    return safe


def _run_tool_hooks(
    *,
    runner: HookRunner,
    session_store: SessionStore | None,
    session_id: str,
    event: str,
    payload: dict[str, Any],
) -> ToolResult | None:
    for result in runner.run_event(event, session_id=session_id, payload=payload):
        event_payload = result.to_event_payload()
        if session_store is not None:
            session_store.record(session_id, "hook_result", event_payload)
        if result.hook.required and not result.ok:
            return ToolResult(
                ok=False,
                content=f"required hook failed: {result.hook.id}: {result.output}",
                data={
                    "hook_blocked": True,
                    "hook_id": result.hook.id,
                    "event": event,
                },
            )
    return None


def _tool_name(tool: Tool) -> str:
    name = getattr(tool, "name", None)
    return str(name) if name else tool.__class__.__name__


def _tool_risk_level(tool: Tool) -> str:
    risk_level = getattr(tool, "risk_level", None)
    value = getattr(risk_level, "value", None)
    return str(value or "low")


def _clip_text(value: str, limit: int = 500) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[truncated]"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return sanitize_tool_payload(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def raise_if_hook_blocked(result: ToolResult) -> None:
    if result.data.get("hook_blocked"):
        raise PermissionDenied(result.content)
