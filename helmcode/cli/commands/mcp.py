from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from helmcode.core.config import McpServerConfig, load_config, save_user_config

console = Console()
app = typer.Typer(help="Manage MCP server configuration.")


@app.command("list")
def list_mcp(
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List configured MCP servers."""
    servers = load_config().mcp_servers
    if output_json:
        _print_json([_server_payload(server, redact=True) for server in servers])
        return
    _print_server_table(servers)


@app.command("show")
def show_mcp(
    server_id: str = typer.Argument(...),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    reveal_env: bool = typer.Option(False, "--reveal-env", help="Print stored env values."),
) -> None:
    """Show one MCP server."""
    server = _find_server(load_config().mcp_servers, server_id)
    if output_json:
        _print_json(_server_payload(server, redact=not reveal_env))
        return
    _print_server_table([server], reveal_env=reveal_env)


@app.command("add")
def add_mcp(
    server_id: str = typer.Argument(...),
    transport: str = typer.Option("stdio", "--transport", help="stdio, http, or sse."),
    command: str | None = typer.Option(None, "--command", help="Stdio command."),
    arg: list[str] = typer.Option(None, "--arg", help="Command argument. Repeatable."),
    url: str | None = typer.Option(None, "--url", help="HTTP/SSE endpoint."),
    env: list[str] = typer.Option(None, "--env", help="Env key=value. Repeatable."),
    cwd: str | None = typer.Option(None, "--cwd", help="Working directory for stdio command."),
    description: str = typer.Option("", "--description", "-d"),
    disabled: bool = typer.Option(False, "--disabled", help="Add server disabled."),
    force: bool = typer.Option(False, "--force", "-f", help="Replace existing server id."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Add or replace an MCP server config."""
    config = load_config()
    servers = [server for server in config.mcp_servers if server.id != server_id]
    if len(servers) != len(config.mcp_servers) and not force:
        raise typer.BadParameter(f"MCP server already exists: {server_id}. Use --force to replace.")
    try:
        server = McpServerConfig(
            id=server_id,
            transport=transport,
            command=command,
            args=arg or [],
            url=url,
            env=_parse_env(env or []),
            cwd=cwd,
            enabled=not disabled,
            description=description,
        )
    except ValidationError as exc:
        raise typer.BadParameter(str(exc)) from exc
    config.mcp_servers = [*servers, server]
    save_user_config(config)
    if output_json:
        _print_json(_server_payload(server, redact=True))
        return
    console.print(f"Saved MCP server: {server.id}")


@app.command("remove")
def remove_mcp(
    server_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Remove an MCP server config."""
    config = load_config()
    remaining = [server for server in config.mcp_servers if server.id != server_id]
    removed = len(remaining) != len(config.mcp_servers)
    if removed and not yes and not typer.confirm(f"Remove MCP server {server_id}?"):
        console.print("Remove cancelled.")
        return
    if removed:
        config.mcp_servers = remaining
        save_user_config(config)
    payload = {"server_id": server_id, "removed": removed}
    if output_json:
        _print_json(payload)
        return
    console.print("Removed." if removed else "MCP server not found.")


@app.command("doctor")
def doctor_mcp(output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON.")) -> None:
    """Validate local MCP server configuration."""
    statuses = [_doctor_payload(server) for server in load_config().mcp_servers]
    if output_json:
        _print_json(statuses)
        return
    table = Table(title="MCP doctor")
    table.add_column("ID")
    table.add_column("Transport")
    table.add_column("Status")
    table.add_column("Details")
    for status in statuses:
        table.add_row(
            str(status["id"]),
            str(status["transport"]),
            "ok" if status["ok"] else "warn",
            str(status["details"]),
        )
    console.print(table)


@app.command("export")
def export_mcp(
    format: str = typer.Option("claude", "--format", help="claude or raw."),
) -> None:
    """Export MCP config for another client."""
    servers = load_config().mcp_servers
    if format == "raw":
        _print_json([_server_payload(server, redact=False) for server in servers])
        return
    if format != "claude":
        raise typer.BadParameter("format must be one of: claude, raw")
    _print_json(_claude_payload(servers))


def _find_server(servers: list[McpServerConfig], server_id: str) -> McpServerConfig:
    for server in servers:
        if server.id == server_id:
            return server
    raise typer.BadParameter(f"unknown MCP server: {server_id}")


def _parse_env(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise typer.BadParameter("--env values must use key=value")
        key, env_value = value.split("=", 1)
        if not key:
            raise typer.BadParameter("--env key cannot be empty")
        parsed[key] = env_value
    return parsed


def _server_payload(server: McpServerConfig, *, redact: bool) -> dict[str, Any]:
    payload = server.model_dump(mode="json")
    if redact and payload.get("env"):
        payload["env"] = {key: "<redacted>" for key in payload["env"]}
    return payload


def _doctor_payload(server: McpServerConfig) -> dict[str, Any]:
    if not server.enabled:
        return {
            "id": server.id,
            "transport": server.transport,
            "ok": True,
            "details": "disabled",
        }
    if server.transport == "stdio":
        found = shutil.which(server.command or "") is not None
        return {
            "id": server.id,
            "transport": server.transport,
            "ok": found,
            "details": f"command found: {server.command}" if found else f"command not found: {server.command}",
        }
    return {
        "id": server.id,
        "transport": server.transport,
        "ok": bool(server.url),
        "details": server.url or "missing url",
    }


def _claude_payload(servers: list[McpServerConfig]) -> dict[str, Any]:
    mcp_servers: dict[str, Any] = {}
    for server in servers:
        if not server.enabled:
            continue
        if server.transport == "stdio":
            mcp_servers[server.id] = {
                "command": server.command,
                "args": server.args,
                **({"env": server.env} if server.env else {}),
                **({"cwd": server.cwd} if server.cwd else {}),
            }
        else:
            mcp_servers[server.id] = {"url": server.url, "transport": server.transport}
    return {"mcpServers": mcp_servers}


def _print_server_table(servers: list[McpServerConfig], *, reveal_env: bool = False) -> None:
    table = Table(title="MCP servers")
    table.add_column("ID")
    table.add_column("Transport")
    table.add_column("Enabled")
    table.add_column("Command/URL")
    table.add_column("Env")
    table.add_column("Description")
    for server in servers:
        command_or_url = server.url or " ".join([server.command or "", *server.args]).strip()
        env_text = ", ".join(
            f"{key}={value if reveal_env else '<redacted>'}"
            for key, value in server.env.items()
        )
        table.add_row(
            server.id,
            server.transport,
            "yes" if server.enabled else "no",
            command_or_url,
            env_text,
            server.description,
        )
    console.print(table)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2, default=str))
