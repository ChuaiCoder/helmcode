from __future__ import annotations

from dataclasses import dataclass

from helmcode.context.file_index import FileIndex
from helmcode.context.workspace import Workspace


@dataclass(slots=True)
class RepoMap:
    workspace: Workspace
    files: list[str]

    @classmethod
    def build(cls, workspace: Workspace, limit: int = 200) -> "RepoMap":
        files = FileIndex(workspace.root_path, workspace.ignored_patterns).list_files(limit=limit)
        return cls(workspace=workspace, files=files)

    def summary(self) -> str:
        file_preview = ", ".join(self.files[:30])
        if len(self.files) > 30:
            file_preview += f", ... ({len(self.files)} files)"
        return f"{self.workspace.project_files_summary}\nFiles: {file_preview or 'none'}"
