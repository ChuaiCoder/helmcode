from __future__ import annotations

from dataclasses import dataclass

from helmcode.agent.loop import AgentLoop
from helmcode.agent.state import AgentPlan, AgentState
from helmcode.context.workspace import Workspace
from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME
from helmcode.memory.session_store import SessionStore
from helmcode.models.provider import ProviderAdapter


@dataclass(slots=True)
class RunResult:
    plan: str
    pending_patch: str | None
    patch_files: list[str]
    applied_files: list[str]
    test_output: str | None
    session_id: str


@dataclass(slots=True)
class PlannedRun:
    task: str
    plan: str
    session_id: str


@dataclass(slots=True)
class PreparedRun:
    plan: str
    pending_patch: str
    patch_files: list[str]
    session_id: str


class RunOrchestrator:
    def __init__(
        self,
        workspace: Workspace,
        provider: ProviderAdapter,
        planning_model_id: str,
        coding_model_id: str,
        permission_mode: str,
        coding_provider: ProviderAdapter | None = None,
        executor: object | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.coding_provider = coding_provider or provider
        self.planning_model_id = planning_model_id
        self.coding_model_id = coding_model_id
        self.permission_mode = permission_mode
        self.external_executor = executor
        self.session_store = session_store

    def run(self, task: str, confirmed: bool, run_tests: bool = True) -> RunResult:
        prepared = self.prepare(task)
        if not confirmed:
            return RunResult(
                plan=prepared.plan,
                pending_patch=prepared.pending_patch,
                patch_files=prepared.patch_files,
                applied_files=[],
                test_output=None,
                session_id=prepared.session_id,
            )
        applied = self.apply_prepared(prepared, run_tests=run_tests)
        return RunResult(
            plan=prepared.plan,
            pending_patch=None,
            patch_files=prepared.patch_files,
            applied_files=applied.applied_files,
            test_output=applied.test_output,
            session_id=prepared.session_id,
        )

    def plan(self, task: str) -> PlannedRun:
        state = AgentState.start(self.workspace.root_path, task)
        self._record(state.session_id, "user_message", {"content": task})
        agent = AgentLoop(
            workspace=self.workspace,
            model_provider=self.provider,
            model_id=self.planning_model_id,
            state=state,
            permission_mode=self.permission_mode,
            coding_model_id=self.coding_model_id,
            coding_provider=self.coding_provider,
        )
        plan = agent.plan(task)
        self._record(state.session_id, "plan_created", {"content": plan.content})
        return PlannedRun(task=task, plan=plan.content, session_id=state.session_id)

    def prepare(self, task: str) -> PreparedRun:
        return self.generate_patch_from_plan(self.plan(task))

    def generate_patch_from_plan(self, planned: PlannedRun) -> PreparedRun:
        state = AgentState.start(self.workspace.root_path, planned.task)
        state.session_id = planned.session_id
        agent = AgentLoop(
            workspace=self.workspace,
            model_provider=self.provider,
            model_id=self.planning_model_id,
            state=state,
            permission_mode=self.permission_mode,
            coding_model_id=self.coding_model_id,
            coding_provider=self.coding_provider,
        )
        state.plan = AgentPlan(content=planned.plan)
        generated_patch = agent.generate_patch(planned.task)
        self._record(
            state.session_id,
            "patch_created",
            {"files": generated_patch.files, "patch": generated_patch.content},
        )
        if state.pending_patch is None:
            raise RuntimeError("Coding model did not produce a pending patch")
        return PreparedRun(
            plan=planned.plan,
            pending_patch=state.pending_patch,
            patch_files=generated_patch.files,
            session_id=state.session_id,
        )

    def apply_prepared(self, prepared: PreparedRun, run_tests: bool = True) -> RunResult:
        state = AgentState.start(self.workspace.root_path, "")
        state.session_id = prepared.session_id
        state.plan = None
        state.pending_patch = prepared.pending_patch
        agent = AgentLoop(
            workspace=self.workspace,
            model_provider=self.provider,
            model_id=self.planning_model_id,
            state=state,
            permission_mode=self.permission_mode,
            coding_model_id=self.coding_model_id,
            coding_provider=self.coding_provider,
        )
        applied_files: list[str] = []
        test_output: str | None = None
        applied_files = agent.apply_pending_patch(confirmed=True)
        self._clear_pending_patch_file()
        self._record(prepared.session_id, "patch_applied", {"files": applied_files})
        if run_tests:
            test_output = self._run_tests(agent)
            self._record(
                prepared.session_id,
                "command_result",
                {"command": "auto-detected tests", "output": test_output},
            )

        return RunResult(
            plan=prepared.plan,
            pending_patch=None,
            patch_files=prepared.patch_files,
            applied_files=applied_files,
            test_output=test_output,
            session_id=prepared.session_id,
        )

    def _run_tests(self, agent: AgentLoop) -> str:
        if self.external_executor is not None:
            return str(self.external_executor.run_tests())
        return agent.executor.run_tests()

    def _record(self, session_id: str, event_type: str, payload: dict[str, object]) -> None:
        if self.session_store is not None:
            self.session_store.record(session_id, event_type, payload)

    def _clear_pending_patch_file(self) -> None:
        patch_path = self.workspace.root_path / SESSION_DIR_NAME / PENDING_PATCH_FILE
        patch_path.unlink(missing_ok=True)
