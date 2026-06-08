from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from helmcode.core.constants import DEFAULT_READ_LIMIT
from helmcode.safety.secret_scanner import SecretScanner
from helmcode.tools.base import Tool, ToolResult


class ReadFileInput(BaseModel):
    path: Path
    start_line: int | None = None
    end_line: int | None = None
    max_chars: int = DEFAULT_READ_LIMIT
    allow_sensitive: bool = False


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a file, optionally restricted to a line range."
    input_schema = ReadFileInput

    def __init__(self, root_path: Path | None = None) -> None:
        self.root_path = root_path.resolve() if root_path else None
        self.secret_scanner = SecretScanner()

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, ReadFileInput)
        path = params.path
        if not path.is_absolute() and self.root_path is not None:
            path = self.root_path / path
        scan = self.secret_scanner.check_path(path)
        if scan.sensitive and not params.allow_sensitive:
            return ToolResult(
                ok=False,
                content=f"Refusing to read sensitive file without confirmation: {scan.reason}",
                data={"sensitive": True},
            )

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        start = max((params.start_line or 1) - 1, 0)
        end = params.end_line if params.end_line is not None else len(lines)
        selected = lines[start:end]
        content = "\n".join(f"{idx + start + 1}: {line}" for idx, line in enumerate(selected))
        if len(content) > params.max_chars:
            content = content[: params.max_chars] + "\n[truncated]"
        return ToolResult(ok=True, content=content, data={"path": str(path), "line_count": len(lines)})
