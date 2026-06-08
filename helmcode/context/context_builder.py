from __future__ import annotations

from dataclasses import dataclass

from helmcode.context.repo_map import RepoMap
from helmcode.context.token_budget import TokenBudget
from helmcode.context.workspace import Workspace


@dataclass(slots=True)
class BuiltContext:
    text: str
    files_considered: list[str]


class ContextBuilder:
    def __init__(self, workspace: Workspace, budget: TokenBudget | None = None) -> None:
        self.workspace = workspace
        self.budget = budget or TokenBudget()

    def build_for_task(self, task: str) -> BuiltContext:
        repo_map = RepoMap.build(self.workspace)
        sections = [
            f"User task:\n{task}",
            f"Workspace:\n{self.workspace.project_files_summary}",
            f"Repository map:\n{repo_map.summary()}",
        ]
        return BuiltContext(text=self.budget.fit(sections), files_considered=repo_map.files)
