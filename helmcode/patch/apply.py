from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from helmcode.patch.parser import Hunk, PatchParser


class PatchApplyError(RuntimeError):
    pass


@dataclass(slots=True)
class PatchApplyResult:
    applied_files: list[str]


def apply_unified_patch(root_path: Path, patch: str) -> PatchApplyResult:
    parsed = PatchParser().parse(patch)
    root = root_path.resolve()
    applied: list[str] = []
    for file_patch in parsed.file_patches:
        target = (root / file_patch.target_path).resolve()
        if not target.is_relative_to(root):
            raise PatchApplyError(f"patch target escapes workspace: {file_patch.target_path}")
        if not target.exists():
            raise PatchApplyError(f"target file does not exist: {file_patch.target_path}")
        original = target.read_text(encoding="utf-8").splitlines(keepends=True)
        updated = _apply_hunks(original, file_patch.hunks, file_patch.target_path)
        target.write_text("".join(updated), encoding="utf-8")
        applied.append(file_patch.target_path)
    return PatchApplyResult(applied_files=applied)


def _apply_hunks(original: list[str], hunks: list[Hunk], path: str) -> list[str]:
    output: list[str] = []
    cursor = 0
    for hunk in hunks:
        start = hunk.old_start - 1
        if start < cursor:
            raise PatchApplyError(f"overlapping hunks in {path}")
        output.extend(original[cursor:start])
        cursor = start
        replacement: list[str] = []
        for line in hunk.lines:
            expected_text = line.text + "\n"
            if line.kind == " ":
                if cursor >= len(original) or original[cursor] != expected_text:
                    raise PatchApplyError(f"context mismatch applying patch to {path}")
                replacement.append(original[cursor])
                cursor += 1
            elif line.kind == "-":
                if cursor >= len(original) or original[cursor] != expected_text:
                    raise PatchApplyError(f"context mismatch applying patch to {path}")
                cursor += 1
            elif line.kind == "+":
                replacement.append(expected_text)
            else:
                raise PatchApplyError(f"unknown hunk line kind {line.kind!r}")
        output.extend(replacement)
    output.extend(original[cursor:])
    return output
