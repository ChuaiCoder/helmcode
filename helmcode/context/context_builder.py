from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from helmcode.context.repo_map import RepoMap
from helmcode.context.token_budget import TokenBudget
from helmcode.context.workspace import Workspace
from helmcode.memory.skill_store import SkillStore, render_skills_for_context
from helmcode.safety.secret_scanner import SecretScanner


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
    ) -> None:
        self.workspace = workspace
        self.budget = budget or TokenBudget()
        self.max_relevant_files = max_relevant_files
        self.max_file_chars = max_file_chars
        self.secret_scanner = SecretScanner()

    def build_for_task(self, task: str, additional_sections: list[str] | None = None) -> BuiltContext:
        repo_map = RepoMap.build(self.workspace)
        explicit_context = self._build_explicit_reference_context(task)
        relevant_files = self._select_relevant_files(task, repo_map.files)
        skill_context = render_skills_for_context(SkillStore(self.workspace.root_path).matching(task))
        sections = [
            f"User task:\n{task}",
            f"Workspace:\n{self.workspace.project_files_summary}",
            f"Repository map:\n{repo_map.summary()}",
        ]
        if skill_context:
            sections.append("Matched skills:\n" + skill_context)
        if additional_sections:
            sections.extend(additional_sections)
        if explicit_context.excerpts:
            sections.append("Explicit @ references:\n" + "\n\n".join(explicit_context.excerpts))
        if explicit_context.warnings:
            sections.append("Context reference warnings:\n" + "\n".join(explicit_context.warnings))
        files_considered = _dedupe([*explicit_context.files, *relevant_files])
        inferred_files = [relative_path for relative_path in relevant_files if relative_path not in explicit_context.files]
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
        excerpts: list[str] = []
        warnings: list[str] = []
        for raw_reference in _parse_context_references(task):
            resolved = _resolve_context_reference(self.workspace.root_path, raw_reference)
            if resolved.warning:
                warnings.append(resolved.warning)
                continue
            if resolved.relative_path is None or resolved.path is None:
                continue
            relative_path = resolved.relative_path
            if relative_path in files:
                continue
            scan = self.secret_scanner.check_path(relative_path)
            if scan.sensitive:
                warnings.append(f"Skipped @{raw_reference}: {scan.reason}")
                continue
            if not resolved.path.is_file():
                warnings.append(f"Skipped @{raw_reference}: not a file")
                continue
            if not _is_text_like(resolved.path):
                warnings.append(f"Skipped @{raw_reference}: unsupported file type")
                continue
            try:
                content = resolved.path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                warnings.append(f"Skipped @{raw_reference}: {exc}")
                continue
            if len(content) > self.max_file_chars:
                content = content[: self.max_file_chars] + "\n[truncated]"
            files.append(relative_path)
            excerpts.append(f"--- {relative_path} ---\n{content}")
        return _ExplicitReferenceContext(files=files, excerpts=excerpts, warnings=warnings)

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
    excerpts: list[str]
    warnings: list[str]


def estimate_explicit_reference_tokens(
    workspace: Workspace,
    task: str,
    *,
    max_file_chars: int = 4_000,
    chars_per_token: int = 4,
) -> int:
    total_chars = 0
    seen: set[str] = set()
    scanner = SecretScanner()
    for raw_reference in _parse_context_references(task):
        resolved = _resolve_context_reference(workspace.root_path, raw_reference)
        if resolved.warning or resolved.path is None or resolved.relative_path is None:
            continue
        if resolved.relative_path in seen:
            continue
        if scanner.check_path(resolved.relative_path).sensitive:
            continue
        if not resolved.path.is_file() or not _is_text_like(resolved.path):
            continue
        try:
            size = len(resolved.path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        seen.add(resolved.relative_path)
        total_chars += min(size, max_file_chars)
    if total_chars <= 0:
        return 0
    return max(1, total_chars // max(chars_per_token, 1))


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
