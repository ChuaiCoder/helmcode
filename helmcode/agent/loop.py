from __future__ import annotations

from dataclasses import dataclass

from helmcode.agent.coder import Coder
from helmcode.agent.executor import Executor
from helmcode.agent.planner import Planner
from helmcode.agent.state import AgentPlan, AgentState
from helmcode.context.workspace import Workspace
from helmcode.models.provider import ModelResponse, ProviderAdapter


@dataclass(slots=True)
class GeneratedPatch:
    content: str
    files: list[str]


class AgentLoop:
    """Small but real agent loop for plan-first local code tasks."""

    def __init__(
        self,
        workspace: Workspace,
        model_provider: ProviderAdapter,
        model_id: str,
        state: AgentState,
        permission_mode: str = "suggest",
        coding_model_id: str | None = None,
        coding_provider: ProviderAdapter | None = None,
    ) -> None:
        self.workspace = workspace
        self.model_provider = model_provider
        self.model_id = model_id
        self.coding_model_id = coding_model_id or model_id
        self.coding_provider = coding_provider or model_provider
        self.state = state
        self.permission_mode = permission_mode
        self.planner = Planner(workspace, model_provider, model_id)
        self.coder = Coder(workspace, self.coding_provider, self.coding_model_id)
        self.executor = Executor(workspace.root_path, permission_mode=permission_mode)

    def plan(self, task: str) -> AgentPlan:
        response: ModelResponse = self.planner.create_plan(task)
        self.state.plan = AgentPlan(content=response.content)
        return self.state.plan

    def prepare_patch(self, patch: str) -> list[str]:
        files = self.executor.prepare_patch(patch)
        self.state.pending_patch = patch
        return files

    def generate_patch(self, task: str) -> GeneratedPatch:
        if self.state.plan is None:
            self.plan(task)
        assert self.state.plan is not None
        response: ModelResponse = self.coder.create_patch(task, self.state.plan.content)
        files = self.prepare_patch(response.content)
        return GeneratedPatch(content=response.content, files=files)

    def apply_pending_patch(self, confirmed: bool) -> list[str]:
        if self.state.pending_patch is None:
            raise RuntimeError("No pending patch to apply")
        files = self.executor.apply_patch(self.state.pending_patch, confirmed=confirmed)
        self.state.patches_applied.extend(files)
        self.state.pending_patch = None
        return files
