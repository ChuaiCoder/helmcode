from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path

from helmcode.core.constants import SESSION_DIR_NAME


DEFAULT_EXCLUDES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".npm-cache",
    "dist",
    "build",
    SESSION_DIR_NAME,
}


class FileIndex:
    def __init__(self, root_path: Path, ignored_patterns: list[str] | None = None) -> None:
        self.root_path = root_path.resolve()
        self.ignored_patterns = ignored_patterns or []
        self._cache_path = self.root_path / SESSION_DIR_NAME / "file_index.json"
        self._cache: dict[str, str] = self._load_cache()
        self._files_cache: list[str] | None = None

    def list_files(self, limit: int = 500, use_cache: bool = True) -> list[str]:
        if use_cache and self._files_cache is not None:
            return self._files_cache[:limit]

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

        self._files_cache = sorted(files)
        return self._files_cache[:limit]

    @property
    def cache_path(self) -> Path:
        return self._cache_path

    @property
    def cached_file_count(self) -> int:
        return len(self._cache)

    def get_changed_files(self) -> list[str]:
        """Get files that have changed since last cache update."""
        changed_files: list[str] = []
        current_files = set(self.list_files(use_cache=False))

        # Check for new or modified files
        for file_path in current_files:
            if file_path not in self._cache:
                changed_files.append(file_path)
            else:
                try:
                    full_path = self.root_path / file_path
                    content_hash = self._compute_file_hash(full_path)
                    if content_hash != self._cache[file_path]:
                        changed_files.append(file_path)
                except (OSError, IOError):
                    changed_files.append(file_path)

        # Check for deleted files
        for cached_file in list(self._cache.keys()):
            if cached_file not in current_files:
                changed_files.append(cached_file)

        return changed_files

    def update_cache(self) -> list[str]:
        """Update cache and return list of changed files."""
        changed_files = self.get_changed_files()

        # Update cache with current file hashes
        new_cache: dict[str, str] = {}
        for file_path in self.list_files(use_cache=False):
            try:
                full_path = self.root_path / file_path
                new_cache[file_path] = self._compute_file_hash(full_path)
            except (OSError, IOError):
                continue

        self._cache = new_cache
        self._save_cache(new_cache)
        return changed_files

    def _load_cache(self) -> dict[str, str]:
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        files = payload.get("files")
        if not isinstance(files, dict):
            return {}
        return {
            str(relative_path): str(content_hash)
            for relative_path, content_hash in files.items()
            if isinstance(relative_path, str) and isinstance(content_hash, str)
        }

    def _save_cache(self, cache: dict[str, str]) -> None:
        try:
            self._cache_path.parent.mkdir(exist_ok=True)
            self._cache_path.write_text(
                json.dumps({"files": cache}, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file content."""
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (OSError, IOError):
            return ""

    def _ignored(self, relative: str, path: Path) -> bool:
        if any(part in DEFAULT_EXCLUDES for part in path.parts):
            return True
        return any(_matches_ignore_pattern(relative, pattern) for pattern in self.ignored_patterns)


def _matches_ignore_pattern(relative: str, pattern: str) -> bool:
    normalized = pattern.replace("\\", "/").strip()
    if not normalized:
        return False
    if normalized.endswith("/"):
        directory = normalized.rstrip("/")
        return relative == directory or relative.startswith(directory + "/")
    if "/" not in normalized:
        return any(fnmatch.fnmatch(part, normalized) for part in Path(relative).parts)
    return fnmatch.fnmatch(relative, normalized)
