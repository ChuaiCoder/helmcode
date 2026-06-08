from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from helmcode.context.file_index import FileIndex
from helmcode.tools.base import Tool, ToolResult


class ListFilesInput(BaseModel):
    root_path: Path = Field(default_factory=Path.cwd)
    limit: int = 500


class ListFilesTool(Tool):
    name = "list_files"
    description = "List workspace files while skipping common generated directories."
    input_schema = ListFilesInput

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, ListFilesInput)
        files = FileIndex(params.root_path).list_files(limit=params.limit)
        return ToolResult(ok=True, content="\n".join(files), data={"files": files})
