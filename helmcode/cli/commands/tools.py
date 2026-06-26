from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import typer
from pydantic.json_schema import PydanticJsonSchemaWarning
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helmcode.memory.session_store import SessionStore
from helmcode.tools.read_file import ReadFileTool
from helmcode.tools.registry import default_tool_registry

console = Console()
app = typer.Typer(help="Inspect and run local tools.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def tools_callback(
    ctx: typer.Context,
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List tools when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        list_tools(output_json=output_json)


@app.command("list")
def list_tools(output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON.")) -> None:
    """List registered local tools."""
    registry = default_tool_registry()
    tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "risk_level": tool.risk_level.value,
            "schema": _tool_schema(tool.input_schema),
        }
        for tool in registry.all()
    ]
    if output_json:
        _print_json(tools)
        return
    table = Table(title="Tools")
    table.add_column("Name")
    table.add_column("Risk")
    table.add_column("Description")
    for tool in tools:
        table.add_row(str(tool["name"]), str(tool["risk_level"]), str(tool["description"]))
    console.print(table)


@app.command("run")
def run_tool(
    tool_name: str = typer.Argument(...),
    input_json: str = typer.Argument("{}", help="Tool input as JSON object."),
    param: list[str] = typer.Option(None, "--param", "-p", help="Input key=value. Repeatable."),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    permission_mode: str = typer.Option("suggest", "--permission"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Run a registered local tool and record an audit event."""
    registry = default_tool_registry()
    tool = registry.get(tool_name)
    if isinstance(tool, ReadFileTool):
        tool.root_path = workspace.resolve()
    raw_input = _parse_input(input_json)
    raw_input.update(_parse_params(param or []))
    raw_input = _with_workspace_defaults(raw_input, workspace.resolve(), permission_mode)
    result = tool.run(raw_input)
    SessionStore(workspace.resolve()).record(
        "tool-cli",
        "tool_result",
        {
            "tool": tool.name,
            "input": _safe_input(raw_input),
            "ok": result.ok,
            "content": result.content,
            "data": result.data,
        },
    )
    payload = {"tool": tool.name, **result.model_dump(mode="json")}
    if output_json:
        _print_json(payload)
        return
    console.print(Panel(result.content or "", title=f"{tool.name}: {'ok' if result.ok else 'failed'}"))


def _parse_input(input_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(input_json)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"input must be JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("input must be a JSON object")
    return payload


def _parse_params(params: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in params:
        if "=" not in item:
            raise typer.BadParameter("--param values must use key=value")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter("--param key cannot be empty")
        parsed[key] = _parse_param_value(value)
    return parsed


def _parse_param_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _with_workspace_defaults(
    payload: dict[str, Any],
    workspace: Path,
    permission_mode: str,
) -> dict[str, Any]:
    if "root_path" not in payload:
        payload["root_path"] = str(workspace)
    if "permission_mode" not in payload:
        payload["permission_mode"] = permission_mode
    return payload


def _safe_input(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload)
    if "patch" in safe:
        safe["patch"] = "<redacted patch>"
    if "output" in safe and isinstance(safe["output"], str) and len(safe["output"]) > 500:
        safe["output"] = safe["output"][:500] + "\n[truncated]"
    return safe


def _tool_schema(schema_type) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PydanticJsonSchemaWarning)
        return schema_type.model_json_schema()


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2, default=str))
