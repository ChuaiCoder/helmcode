from __future__ import annotations

from dataclasses import dataclass, field

from helmcode.context.file_index import FileIndex
from helmcode.context.workspace import Workspace


@dataclass
class RepoMap:
    workspace: Workspace
    files: list[str]
    _file_index: FileIndex = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._file_index = FileIndex(self.workspace.root_path, self.workspace.ignored_patterns)

    @classmethod
    def build(cls, workspace: Workspace, limit: int = 200) -> "RepoMap":
        file_index = FileIndex(workspace.root_path, workspace.ignored_patterns)
        files = file_index.list_files(limit=limit)
        repo_map = cls(workspace=workspace, files=files)
        repo_map._file_index = file_index
        return repo_map

    def rebuild_incremental(self, limit: int = 200) -> "RepoMap":
        """Rebuild repo map using incremental updates."""
        changed_files = self._file_index.update_cache()

        if not changed_files:
            return self

        # Rebuild file list from cache
        self.files = self._file_index.list_files(limit=limit)
        return self

    def get_changed_files(self) -> list[str]:
        """Get files that have changed since last update."""
        return self._file_index.get_changed_files()

    def summary(self) -> str:
        file_preview = ", ".join(self.files[:30])
        if len(self.files) > 30:
            file_preview += f", ... ({len(self.files)} files)"
        return f"{self.workspace.project_files_summary}\nFiles: {file_preview or 'none'}"
