from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from helmcode.core.config import McpServerConfig
from helmcode.safety.risk import RiskLevel
from helmcode.tools.base import ToolResult

MCP_PROTOCOL_VERSION = "2024-11-05"


class McpRuntimeError(RuntimeError):
    pass


@dataclass(slots=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class McpCallTool:
    description = "Call a configured MCP tool."
    risk_level = RiskLevel.MEDIUM

    def __init__(self, server: McpServerConfig, timeout_seconds: float = 30.0) -> None:
        self.server = server
        self.timeout_seconds = timeout_seconds
        self.name = f"mcp:{server.id}"

    def run(self, raw_input: dict[str, Any]) -> ToolResult:
        tool_name = raw_input.get("tool_name")
        arguments = raw_input.get("arguments", {})
        if not isinstance(tool_name, str) or not tool_name.strip():
            return ToolResult(ok=False, content="MCP tool_name is required", data={})
        if not isinstance(arguments, dict):
            return ToolResult(ok=False, content="MCP arguments must be a JSON object", data={})
        try:
            result = call_mcp_tool(
                self.server,
                tool_name=tool_name,
                arguments=arguments,
                timeout_seconds=self.timeout_seconds,
            )
        except McpRuntimeError as exc:
            return ToolResult(ok=False, content=str(exc), data={})
        return ToolResult(ok=True, content=_content_text(result), data={"result": result})


def list_mcp_tools(
    server: McpServerConfig,
    *,
    timeout_seconds: float = 30.0,
) -> list[McpToolInfo]:
    with StdioMcpClient(server, timeout_seconds=timeout_seconds) as client:
        payload = client.request("tools/list", {})
    tools = payload.get("tools")
    if not isinstance(tools, list):
        raise McpRuntimeError("MCP tools/list response did not contain tools")
    result: list[McpToolInfo] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = item.get("description")
        input_schema = item.get("inputSchema") or item.get("input_schema") or {}
        result.append(
            McpToolInfo(
                name=name,
                description=description if isinstance(description, str) else "",
                input_schema=input_schema if isinstance(input_schema, dict) else {},
            )
        )
    return result


def call_mcp_tool(
    server: McpServerConfig,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    with StdioMcpClient(server, timeout_seconds=timeout_seconds) as client:
        return client.request("tools/call", {"name": tool_name, "arguments": arguments})


class StdioMcpClient:
    def __init__(self, server: McpServerConfig, *, timeout_seconds: float = 30.0) -> None:
        if server.transport != "stdio":
            raise McpRuntimeError(f"MCP runtime only supports stdio servers: {server.id}")
        if not server.command:
            raise McpRuntimeError(f"stdio MCP server is missing command: {server.id}")
        self.server = server
        self.timeout_seconds = timeout_seconds
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1

    def __enter__(self) -> "StdioMcpClient":
        env = os.environ.copy()
        env.update(_resolved_env(self.server.env))
        self.process = subprocess.Popen(
            [self.server.command or "", *self.server.args],
            cwd=_server_cwd(self.server),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "helmcode", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized", {})
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        response = self._read_response(request_id)
        if "error" in response:
            raise McpRuntimeError(f"MCP {method} failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpRuntimeError(f"MCP {method} response did not contain an object result")
        return result

    def _write(self, payload: dict[str, Any]) -> None:
        process = self._process()
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _read_response(self, request_id: int) -> dict[str, Any]:
        process = self._process()
        assert process.stdout is not None
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise McpRuntimeError(_process_exit_message(process))
            remaining = max(deadline - time.monotonic(), 0.01)
            line = _readline_with_timeout(process.stdout, remaining)
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("id") == request_id:
                return payload
        raise McpRuntimeError(f"MCP server timed out after {self.timeout_seconds}s")

    def _process(self) -> subprocess.Popen[str]:
        if self.process is None:
            raise McpRuntimeError("MCP process is not running")
        return self.process


def _server_cwd(server: McpServerConfig) -> str | None:
    if not server.cwd:
        return None
    return str(Path(server.cwd).expanduser())


def _resolved_env(values: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        result[key] = os.path.expandvars(value)
    return result


def _process_exit_message(process: subprocess.Popen[str]) -> str:
    stderr = ""
    if process.stderr is not None:
        try:
            stderr = process.stderr.read().strip()
        except Exception:
            stderr = ""
    detail = stderr or f"exit code {process.returncode}"
    return f"MCP server exited before responding: {detail}"


def _readline_with_timeout(stream, timeout_seconds: float) -> str | None:
    lines: queue.Queue[str | None] = queue.Queue(maxsize=1)

    def read_line() -> None:
        try:
            lines.put(stream.readline())
        except Exception:
            lines.put(None)

    thread = threading.Thread(target=read_line, daemon=True)
    thread.start()
    try:
        return lines.get(timeout=timeout_seconds)
    except queue.Empty:
        return None


def _content_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        if text_parts:
            return "\n".join(text_parts)
    return json.dumps(result, ensure_ascii=False, indent=2)
