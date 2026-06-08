from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath


class PatchParseError(ValueError):
    pass


@dataclass(slots=True)
class HunkLine:
    kind: str
    text: str


@dataclass(slots=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[HunkLine] = field(default_factory=list)


@dataclass(slots=True)
class FilePatch:
    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def target_path(self) -> str:
        return _strip_prefix(self.new_path if self.new_path != "/dev/null" else self.old_path)


@dataclass(slots=True)
class ParsedPatch:
    file_patches: list[FilePatch]

    @property
    def files(self) -> list[str]:
        return [file_patch.target_path for file_patch in self.file_patches]


HUNK_RE = re.compile(r"@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


class PatchParser:
    def parse(self, patch: str) -> ParsedPatch:
        lines = patch.splitlines()
        file_patches: list[FilePatch] = []
        current_file: FilePatch | None = None
        current_hunk: Hunk | None = None
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if line.startswith("--- "):
                if idx + 1 >= len(lines) or not lines[idx + 1].startswith("+++ "):
                    raise PatchParseError("unified diff file header must include --- and +++ lines")
                old_path = line[4:].split("\t", 1)[0].strip()
                new_path = lines[idx + 1][4:].split("\t", 1)[0].strip()
                current_file = FilePatch(old_path=old_path, new_path=new_path)
                file_patches.append(current_file)
                current_hunk = None
                idx += 2
                continue
            if line.startswith("@@ "):
                if current_file is None:
                    raise PatchParseError("hunk found before file header")
                match = HUNK_RE.match(line)
                if not match:
                    raise PatchParseError(f"invalid hunk header: {line}")
                current_hunk = Hunk(
                    old_start=int(match.group("old_start")),
                    old_count=int(match.group("old_count") or "1"),
                    new_start=int(match.group("new_start")),
                    new_count=int(match.group("new_count") or "1"),
                )
                current_file.hunks.append(current_hunk)
                idx += 1
                continue
            if current_hunk is not None and line[:1] in {" ", "-", "+"}:
                current_hunk.lines.append(HunkLine(kind=line[0], text=line[1:]))
                idx += 1
                continue
            if line.startswith("\\ No newline at end of file"):
                idx += 1
                continue
            if not line.strip():
                idx += 1
                continue
            raise PatchParseError(f"unexpected patch line: {line}")

        if not file_patches:
            raise PatchParseError("patch does not contain any file changes")
        for file_patch in file_patches:
            if not file_patch.hunks:
                raise PatchParseError(f"file patch has no hunks: {file_patch.target_path}")
            _validate_safe_relative(file_patch.target_path)
        return ParsedPatch(file_patches=file_patches)


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _validate_safe_relative(path: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise PatchParseError(f"unsafe patch target path: {path}")
