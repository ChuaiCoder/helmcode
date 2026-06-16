from __future__ import annotations

from dataclasses import dataclass

from helmcode.agent.executor import TestRunResult
from helmcode.agent.loop import AgentLoop
from helmcode.agent.reviewer import Reviewer
from helmcode.agent.state import AgentPlan, AgentState
from helmcode.context.workspace import Workspace
from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME
from helmcode.core.exceptions import PermissionDenied
from helmcode.memory.session_store import SessionStore
from helmcode.models.provider import ProviderAdapter
from helmcode.safety.permissions import PermissionMode


@dataclass(slots=True)
class RunResult:
    plan: str
    pending_patch: str | None
    patch_files: list[str]
    applied_files: list[str]
    test_output: str | None
    session_id: str
    repair_attempts: int = 0
    review: str | None = None


@dataclass(slots=True)
class PlannedRun:
    task: str
    plan: str
    session_id: str


@dataclass(slots=True)
class PreparedRun:
    task: str
    plan: str
    pending_patch: str
    patch_files: list[str]
    session_id: str
    review: str | None = None


class RunOrchestrator:
    def __init__(
        self,
        workspace: Workspace,
        provider: ProviderAdapter,
        planning_model_id: str,
        coding_model_id: str,
        permission_mode: str,
        coding_provider: ProviderAdapter | None = None,
        review_provider: ProviderAdapter | None = None,
        review_model_id: str | None = None,
        executor: object | None = None,
        session_store: SessionStore | None = None,
        max_repair_attempts: int = 3,
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.coding_provider = coding_provider or provider
        self.review_provider = review_provider
        self.planning_model_id = planning_model_id
        self.coding_model_id = coding_model_id
        self.review_model_id = review_model_id
        self.permission_mode = permission_mode
        self.mode = PermissionMode.normalize(permission_mode)
        self.external_executor = executor
        self.session_store = session_store
        self.max_repair_attempts = max_repair_attempts

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
                repair_attempts=0,
                review=prepared.review,
            )
        applied = self.apply_prepared(prepared, run_tests=run_tests)
        return RunResult(
            plan=prepared.plan,
            pending_patch=None,
            patch_files=prepared.patch_files,
            applied_files=applied.applied_files,
            test_output=applied.test_output,
            session_id=prepared.session_id,
            repair_attempts=applied.repair_attempts,
            review=prepared.review,
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
            executor=self.external_executor,
        )
        plan = agent.plan(task)
        self._record(state.session_id, "plan_created", {"content": plan.content})
        return PlannedRun(task=task, plan=plan.content, session_id=state.session_id)

    def prepare(self, task: str) -> PreparedRun:
        return self.generate_patch_from_plan(self.plan(task))

    def generate_patch_from_plan(self, planned: PlannedRun) -> PreparedRun:
        if not self.mode.can_generate_patch:
            raise PermissionDenied(f"{self.permission_mode} mode blocks patch generation")
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
            executor=self.external_executor,
        )
        state.plan = AgentPlan(content=planned.plan)
        generated_patch = agent.generate_patch(planned.task)
        self._record(
            state.session_id,
            "patch_created",
            {"files": generated_patch.files, "patch": generated_patch.content},
        )
        review = self._review_patch(state.session_id, generated_patch.content)
        if state.pending_patch is None:
            raise RuntimeError("Coding model did not produce a pending patch")
        return PreparedRun(
            task=planned.task,
            plan=planned.plan,
            pending_patch=state.pending_patch,
            patch_files=generated_patch.files,
            session_id=state.session_id,
            review=review,
        )

    def apply_prepared(self, prepared: PreparedRun, run_tests: bool = True) -> RunResult:
        if not self.mode.can_apply_after_confirmation:
            raise PermissionDenied(f"{self.permission_mode} mode blocks patch application")
        state = AgentState.start(self.workspace.root_path, "")
        state.session_id = prepared.session_id
        state.plan = AgentPlan(content=prepared.plan)
        state.pending_patch = prepared.pending_patch
        agent = AgentLoop(
            workspace=self.workspace,
            model_provider=self.provider,
            model_id=self.planning_model_id,
            state=state,
            permission_mode=self.permission_mode,
            coding_model_id=self.coding_model_id,
            coding_provider=self.coding_provider,
            executor=self.external_executor,
        )
        applied_files: list[str] = []
        test_output: str | None = None
        applied_files = agent.apply_pending_patch(confirmed=True)
        self._clear_pending_patch_file()
        self._record(prepared.session_id, "patch_applied", {"files": applied_files})
        repair_attempts = 0
        if run_tests:
            test_result = self._run_tests(agent)
            test_output = test_result.output
            self._record(
                prepared.session_id,
                "command_result",
                {"command": "auto-detected tests", "ok": test_result.ok, "output": test_output},
            )
            while not test_result.ok and repair_attempts < self.max_repair_attempts:
                repair_attempts += 1
                repair_patch = agent.generate_repair_patch(prepared.task, test_result.output)
                self._record(
                    prepared.session_id,
                    "patch_created",
                    {
                        "repair_attempt": repair_attempts,
                        "files": repair_patch.files,
                        "patch": repair_patch.content,
                    },
                )
                repaired_files = agent.apply_pending_patch(confirmed=True)
                applied_files.extend(repaired_files)
                self._clear_pending_patch_file()
                self._record(
                    prepared.session_id,
                    "patch_applied",
                    {"repair_attempt": repair_attempts, "files": repaired_files},
                )
                test_result = self._run_tests(agent)
                test_output = test_result.output
                self._record(
                    prepared.session_id,
                    "command_result",
                    {
                        "command": "auto-detected tests",
                        "repair_attempt": repair_attempts,
                        "ok": test_result.ok,
                        "output": test_result.output,
                    },
                )

        return RunResult(
            plan=prepared.plan,
            pending_patch=None,
            patch_files=prepared.patch_files,
            applied_files=applied_files,
            test_output=test_output,
            session_id=prepared.session_id,
            repair_attempts=repair_attempts,
            review=prepared.review,
        )

    def _run_tests(self, agent: AgentLoop) -> TestRunResult:
        if self.external_executor is not None:
            return self._normalize_test_result(self.external_executor.run_tests())
        return self._normalize_test_result(agent.executor.run_tests())

    def _normalize_test_result(self, raw: object) -> TestRunResult:
        if isinstance(raw, TestRunResult):
            return raw
        if isinstance(raw, tuple) and len(raw) == 2:
            ok, output = raw
            return TestRunResult(ok=bool(ok), output=str(output))
        return TestRunResult(ok=True, output=str(raw))

    def _record(self, session_id: str, event_type: str, payload: dict[str, object]) -> None:
        if self.session_store is not None:
            self.session_store.record(session_id, event_type, payload)

    def _clear_pending_patch_file(self) -> None:
        patch_path = self.workspace.root_path / SESSION_DIR_NAME / PENDING_PATCH_FILE
        patch_path.unlink(missing_ok=True)

    def _review_patch(self, session_id: str, patch: str) -> str | None:
        if self.review_provider is None or self.review_model_id is None:
            return None
        review = Reviewer(self.review_provider, self.review_model_id).review_patch(patch)
        self._record(session_id, "patch_reviewed", {"content": review.content})
        return review.content
