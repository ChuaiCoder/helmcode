from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from helmcode.context.repo_map import RepoMap
from helmcode.context.token_budget import TokenBudget
from helmcode.context.workspace import Workspace
from helmcode.memory.pinned_memory import PinnedMemoryStore, render_pinned_memory_for_context
from helmcode.memory.skill_store import SkillStore, render_skills_for_context
from helmcode.safety.secret_scanner import SecretScanner


IGNORED_CONTEXT_DIRS = {".git", ".helmcode", ".pytest_cache", "__pycache__", "node_modules", ".venv"}


@dataclass(slots=True)
class BuiltContext:
    text: str
    files_considered: list[str]
    explicit_references: list[str] | None = None
    warnings: list[str] | None = None


class ContextBuilder:
    def __init__(
        self,
        workspace: Workspace,
        budget: TokenBudget | None = None,
        max_relevant_files: int = 4,
        max_file_chars: int = 4_000,
        max_explicit_files: int = 8,
    ) -> None:
        self.workspace = workspace
        self.budget = budget or TokenBudget()
        self.max_relevant_files = max_relevant_files
        self.max_file_chars = max_file_chars
        self.max_explicit_files = max_explicit_files
        self.secret_scanner = SecretScanner()

    def build_for_task(self, task: str, additional_sections: list[str] | None = None) -> BuiltContext:
        repo_map = RepoMap.build(self.workspace)
        explicit_context = self._build_explicit_reference_context(task)
        relevant_files = self._select_relevant_files(task, repo_map.files)
        pinned_memory = render_pinned_memory_for_context(PinnedMemoryStore(self.workspace.root_path).list())
        skill_context = render_skills_for_context(SkillStore(self.workspace.root_path).matching(task))
        sections = [
            f"User task:\n{task}",
            f"Workspace:\n{self.workspace.project_files_summary}",
            f"Repository map:\n{repo_map.summary()}",
        ]
        if pinned_memory:
            sections.append("Pinned project memory:\n" + pinned_memory)
        if skill_context:
            sections.append("Matched skills:\n" + skill_context)
        if additional_sections:
            sections.extend(additional_sections)
        if explicit_context.excerpts:
            sections.append("Explicit @ references:\n" + "\n\n".join(explicit_context.excerpts))
        if explicit_context.warnings:
            sections.append("Context reference warnings:\n" + "\n".join(explicit_context.warnings))
        inferred_files = [
            relative_path
            for relative_path in relevant_files
            if relative_path not in explicit_context.files
            and not _is_under_any_directory(relative_path, explicit_context.directories)
        ]
        files_considered = _dedupe([*explicit_context.files, *inferred_files])
        excerpts = self._build_file_excerpts(inferred_files)
        if excerpts:
            sections.append("Relevant file excerpts:\n" + "\n\n".join(excerpts))
        return BuiltContext(
            text=self.budget.fit(sections),
            files_considered=files_considered,
            explicit_references=explicit_context.files,
            warnings=explicit_context.warnings,
        )

    def _build_explicit_reference_context(self, task: str) -> "_ExplicitReferenceContext":
        files: list[str] = []
        directories: list[str] = []
        excerpts: list[str] = []
        warnings: list[str] = []
        for raw_reference in _parse_context_references(task):
            remaining = self.max_explicit_files - len(files)
            if remaining <= 0:
                warnings.append(f"Skipped @{raw_reference}: explicit reference file limit reached")
                continue
            resolved = _resolve_context_reference(self.workspace.root_path, raw_reference)
            if resolved.warning:
                warnings.append(resolved.warning)
                continue
            if resolved.relative_path is None or resolved.path is None:
                continue
            if self.secret_scanner.check_path(resolved.relative_path).sensitive:
                reason = self.secret_scanner.check_path(resolved.relative_path).reason
                warnings.append(f"Skipped @{raw_reference}: {reason}")
                continue
            if resolved.path.is_dir():
                directories.append(resolved.relative_path)
                candidates = _directory_reference_files(
                    resolved.path,
                    self.workspace.root_path,
                    self.secret_scanner,
                    limit=remaining,
                )
                if not candidates.files:
                    warnings.append(f"Skipped @{raw_reference}: no text files found")
                    continue
                for relative_path, path in candidates.files:
                    if relative_path in files:
                        continue
                    if self._append_explicit_file(raw_reference, relative_path, path, files, excerpts, warnings):
                        remaining -= 1
                    if remaining <= 0:
                        break
                if candidates.truncated:
                    warnings.append(
                        f"Truncated @{raw_reference}: only included first {len(candidates.files)} files"
                    )
                continue
            if not resolved.path.is_file():
                warnings.append(f"Skipped @{raw_reference}: not a file or directory")
                continue
            self._append_explicit_file(raw_reference, resolved.relative_path, resolved.path, files, excerpts, warnings)
        return _ExplicitReferenceContext(files=files, directories=directories, excerpts=excerpts, warnings=warnings)

    def _append_explicit_file(
        self,
        raw_reference: str,
        relative_path: str,
        path: Path,
        files: list[str],
        excerpts: list[str],
        warnings: list[str],
    ) -> bool:
        if relative_path in files:
            return False
        scan = self.secret_scanner.check_path(relative_path)
        if scan.sensitive:
            warnings.append(f"Skipped @{raw_reference}: {scan.reason}")
            return False
        if not _is_text_like(path):
            warnings.append(f"Skipped @{raw_reference}: unsupported file type")
            return False
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            warnings.append(f"Skipped @{raw_reference}: {exc}")
            return False
        if len(content) > self.max_file_chars:
            content = content[: self.max_file_chars] + "\n[truncated]"
        files.append(relative_path)
        excerpts.append(f"--- {relative_path} ---\n{content}")
        return True

    def _select_relevant_files(self, task: str, files: list[str]) -> list[str]:
        terms = _task_terms(task)
        scored: list[tuple[int, str]] = []
        for relative_path in files:
            if self.secret_scanner.check_path(relative_path).sensitive:
                continue
            path = self.workspace.root_path / relative_path
            if not _is_text_like(path):
                continue
            searchable = _searchable_path_text(relative_path)
            score = sum(1 for term in terms if term in searchable)
            if score:
                scored.append((score, relative_path))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [relative_path for _score, relative_path in scored[: self.max_relevant_files]]

    def _build_file_excerpts(self, files: list[str]) -> list[str]:
        excerpts: list[str] = []
        for relative_path in files:
            path = self.workspace.root_path / relative_path
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if len(content) > self.max_file_chars:
                content = content[: self.max_file_chars] + "\n[truncated]"
            excerpts.append(f"--- {relative_path} ---\n{content}")
        return excerpts


def _task_terms(task: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[A-Za-z0-9_]+", task.lower())
        if len(term) >= 3
    }


def _searchable_path_text(relative_path: str) -> str:
    path = Path(relative_path)
    parts = [path.as_posix().lower(), path.stem.lower(), *[part.lower() for part in path.parts]]
    return " ".join(parts).replace("-", " ").replace("_", " ")


def _is_text_like(path: Path) -> bool:
    return path.suffix.lower() in {
        ".py",
        ".md",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".txt",
        ".ini",
        ".cfg",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".css",
        ".html",
    }


@dataclass(slots=True)
class _ResolvedContextReference:
    path: Path | None = None
    relative_path: str | None = None
    warning: str | None = None


@dataclass(slots=True)
class _ExplicitReferenceContext:
    files: list[str]
    directories: list[str]
    excerpts: list[str]
    warnings: list[str]


@dataclass(slots=True)
class _DirectoryReferenceFiles:
    files: list[tuple[str, Path]]
    truncated: bool


def estimate_explicit_reference_tokens(
    workspace: Workspace,
    task: str,
    *,
    max_file_chars: int = 4_000,
    max_explicit_files: int = 8,
    chars_per_token: int = 4,
) -> int:
    total_chars = 0
    seen: set[str] = set()
    scanner = SecretScanner()
    for raw_reference in _parse_context_references(task):
        remaining = max_explicit_files - len(seen)
        if remaining <= 0:
            break
        resolved = _resolve_context_reference(workspace.root_path, raw_reference)
        if resolved.warning or resolved.path is None or resolved.relative_path is None:
            continue
        if scanner.check_path(resolved.relative_path).sensitive:
            continue
        if resolved.path.is_dir():
            candidates = _directory_reference_files(
                resolved.path,
                workspace.root_path,
                scanner,
                limit=remaining,
            ).files
        elif resolved.path.is_file():
            candidates = [(resolved.relative_path, resolved.path)]
        else:
            continue
        for relative_path, path in candidates:
            if relative_path in seen:
                continue
            if not path.is_file() or not _is_text_like(path):
                continue
            try:
                size = len(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            seen.add(relative_path)
            total_chars += min(size, max_file_chars)
            if len(seen) >= max_explicit_files:
                break
    if total_chars <= 0:
        return 0
    return max(1, total_chars // max(chars_per_token, 1))


def _directory_reference_files(
    directory: Path,
    root: Path,
    scanner: SecretScanner,
    *,
    limit: int,
) -> _DirectoryReferenceFiles:
    files: list[tuple[str, Path]] = []
    truncated = False
    root_resolved = root.resolve()
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        if any(part in IGNORED_CONTEXT_DIRS for part in path.parts):
            continue
        try:
            relative_path = path.resolve().relative_to(root_resolved).as_posix()
        except (OSError, ValueError):
            continue
        if scanner.check_path(relative_path).sensitive:
            continue
        if not _is_text_like(path):
            continue
        if len(files) >= limit:
            truncated = True
            break
        files.append((relative_path, path))
    return _DirectoryReferenceFiles(files=files, truncated=truncated)


def _parse_context_references(task: str) -> list[str]:
    references: list[str] = []
    for match in re.finditer(r"(?<!\S)@([^\s]+)", task):
        reference = match.group(1).strip().rstrip(".,;:)]}")
        if reference:
            references.append(reference)
    return references


def _resolve_context_reference(root: Path, reference: str) -> _ResolvedContextReference:
    raw_path = Path(reference)
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        resolved = candidate.resolve()
        root_resolved = root.resolve()
    except OSError as exc:
        return _ResolvedContextReference(warning=f"Skipped @{reference}: {exc}")
    if resolved != root_resolved and root_resolved not in resolved.parents:
        return _ResolvedContextReference(warning=f"Skipped @{reference}: outside workspace")
    try:
        relative_path = resolved.relative_to(root_resolved).as_posix()
    except ValueError:
        return _ResolvedContextReference(warning=f"Skipped @{reference}: outside workspace")
    if not resolved.exists():
        return _ResolvedContextReference(warning=f"Skipped @{reference}: file not found")
    return _ResolvedContextReference(path=resolved, relative_path=relative_path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _is_under_any_directory(relative_path: str, directories: list[str]) -> bool:
    normalized_path = Path(relative_path).as_posix()
    for directory in directories:
        normalized_directory = Path(directory).as_posix()
        prefix = "" if normalized_directory == "." else f"{normalized_directory.rstrip('/')}/"
        if prefix and normalized_path.startswith(prefix):
            return True
        if normalized_directory == ".":
            return True
    return False
