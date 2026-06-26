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
        excerpts = self._build_file_excerpts(relevant_files)
        if excerpts:
            sections.append("Relevant file excerpts:\n" + "\n\n".join(excerpts))
        return BuiltContext(text=self.budget.fit(sections), files_considered=relevant_files)

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
