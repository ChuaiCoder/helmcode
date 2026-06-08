from __future__ import annotations

from pathlib import Path


class ProjectMemory:
    """Placeholder for local, repo-scoped notes without cloud sync."""

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
