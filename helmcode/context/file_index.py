from __future__ import annotations

import fnmatch
from pathlib import Path


DEFAULT_EXCLUDES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
}


class FileIndex:
    def __init__(self, root_path: Path, ignored_patterns: list[str] | None = None) -> None:
        self.root_path = root_path.resolve()
        self.ignored_patterns = ignored_patterns or []

    def list_files(self, limit: int = 500) -> list[str]:
        files: list[str] = []
        for path in self.root_path.rglob("*"):
            if len(files) >= limit:
                break
            if path.is_dir():
                continue
            relative = path.relative_to(self.root_path).as_posix()
            if self._ignored(relative, path):
                continue
            files.append(relative)
        return sorted(files)

    def _ignored(self, relative: str, path: Path) -> bool:
        if any(part in DEFAULT_EXCLUDES for part in path.parts):
            return True
        return any(fnmatch.fnmatch(relative, pattern) for pattern in self.ignored_patterns)
