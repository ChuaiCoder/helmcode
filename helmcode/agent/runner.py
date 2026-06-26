from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from helmcode.agent.allocation import AgentAssignment, TaskAllocation
from helmcode.agent.executor import TestRunResult
from helmcode.agent.loop import AgentLoop
from helmcode.agent.reviewer import Reviewer
from helmcode.agent.runtime import AgentRuntime
from helmcode.agent.session import AgentSession
from helmcode.agent.state import AgentPlan, AgentState
from helmcode.context.context_builder import ContextBuilder
from helmcode.context.workspace import Workspace
from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME
from helmcode.core.exceptions import ModelError, PermissionDenied
from helmcode.memory.coding_plan_budget import DEFAULT_BUDGET_KEY
from helmcode.memory.hooks import HookRunner
from helmcode.memory.preplan_cache import PreplanCache
from helmcode.memory.session_store import SessionStore
from helmcode.models.provider import ChatMessage, ModelResponse, ProviderAdapter
from helmcode.models.quota import (
    TASK_CODE_PATCH,
    TASK_PLAN,
    TASK_REPAIR,
    TASK_REPO_SCAN,
    TASK_REVIEW,
    TASK_SUMMARIZE,
    ModelSelection,
)
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
        runtime: AgentRuntime | None = None,
        max_repair_attempts: int = 3,
        block_on_allocation: bool = True,
        allocation_include_repair: bool = False,
        max_cost_score: int | None = None,
        session_budget_score: int | None = None,
        budget_key: str = DEFAULT_BUDGET_KEY,
        preplan_cache_enabled: bool = True,
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
        self.runtime = runtime
        self.max_repair_attempts = max_repair_attempts
        self.block_on_allocation = block_on_allocation
        self.allocation_include_repair = allocation_include_repair
        self.max_cost_score = max_cost_score
        self.session_budget_score = session_budget_score
        self.budget_key = budget_key
        self.preplan_cache_enabled = preplan_cache_enabled

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
        session = self._session_from_state(state, task)
        self._record(state.session_id, "user_message", {"content": task})
        self._run_hooks(session, "pre_plan", {"task": task})
        allocation = self._allocate_task(session, task)
        preplan_context = self._run_preplan_agents(session, task, allocation)
        selection = self._select_model(
            session=session,
            role="planning",
            task_type=TASK_PLAN,
            task=task,
            fallback_model_id=self.planning_model_id,
            default_provider=self.provider,
        )
        planning_provider = self._provider_for(selection, self.provider)
        agent = AgentLoop(
            workspace=self.workspace,
            model_provider=planning_provider,
            model_id=selection.model_id,
            state=state,
            permission_mode=self.permission_mode,
            coding_model_id=self.coding_model_id,
            coding_provider=self.coding_provider,
            executor=self.external_executor,
        )
        plan = agent.plan(task, preplan_context=preplan_context)
        self._record_model_call(session, selection, agent.last_plan_response)
        self._record(state.session_id, "plan_created", {"content": plan.content})
        self._run_hooks(session, "post_plan", {"task": task, "plan": plan.content})
        return PlannedRun(task=task, plan=plan.content, session_id=state.session_id)

    def prepare(self, task: str) -> PreparedRun:
        return self.generate_patch_from_plan(self.plan(task))

    def generate_patch_from_plan(self, planned: PlannedRun) -> PreparedRun:
        if not self.mode.can_generate_patch:
            raise PermissionDenied(f"{self.permission_mode} mode blocks patch generation")
        state = AgentState.start(self.workspace.root_path, planned.task)
        state.session_id = planned.session_id
        session = self._session_from_state(state, planned.task)
        self._run_hooks(session, "pre_patch", {"task": planned.task, "plan": planned.plan})
        selection = self._select_model(
            session=session,
            role="coding",
            task_type=TASK_CODE_PATCH,
            task=planned.task,
            fallback_model_id=self.coding_model_id,
            default_provider=self.coding_provider,
        )
        coding_provider = self._provider_for(selection, self.coding_provider)
        agent = AgentLoop(
            workspace=self.workspace,
            model_provider=self.provider,
            model_id=self.planning_model_id,
            state=state,
            permission_mode=self.permission_mode,
            coding_model_id=selection.model_id,
            coding_provider=coding_provider,
            executor=self.external_executor,
        )
        state.plan = AgentPlan(content=planned.plan)
        generated_patch = agent.generate_patch(planned.task)
        self._record_model_call(session, selection, generated_patch.response)
        self._record(
            state.session_id,
            "patch_created",
            {"files": generated_patch.files, "patch": generated_patch.content},
        )
        self._run_hooks(
            session,
            "post_patch",
            {"task": planned.task, "files": generated_patch.files},
        )
        review = self._review_patch(
            session=session,
            patch=generated_patch.content,
            coding_model_id=selection.model_id,
        )
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
        session = self._session_from_state(state, prepared.task)
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
        self._run_hooks(session, "post_apply", {"task": prepared.task, "files": applied_files})
        repair_attempts = 0
        if run_tests:
            test_result = self._run_tests(agent)
            test_output = test_result.output
            self._record(
                prepared.session_id,
                "command_result",
                {"command": "auto-detected tests", "ok": test_result.ok, "output": test_output},
            )
            self._run_hooks(
                session,
                "post_test",
                {"task": prepared.task, "ok": test_result.ok, "output": test_output},
            )
            while not test_result.ok and repair_attempts < self.max_repair_attempts:
                repair_attempts += 1
                repair_selection = self._select_model(
                    session=session,
                    role="coding",
                    task_type=TASK_REPAIR,
                    task=prepared.task,
                    fallback_model_id=self.coding_model_id,
                    default_provider=self.coding_provider,
                )
                repair_provider = self._provider_for(repair_selection, self.coding_provider)
                repair_agent = AgentLoop(
                    workspace=self.workspace,
                    model_provider=self.provider,
                    model_id=self.planning_model_id,
                    state=state,
                    permission_mode=self.permission_mode,
                    coding_model_id=repair_selection.model_id,
                    coding_provider=repair_provider,
                    executor=self.external_executor,
                )
                repair_patch = repair_agent.generate_repair_patch(prepared.task, test_result.output)
                self._record_model_call(session, repair_selection, repair_patch.response)
                self._record(
                    prepared.session_id,
                    "patch_created",
                    {
                        "repair_attempt": repair_attempts,
                        "files": repair_patch.files,
                        "patch": repair_patch.content,
                    },
                )
                repaired_files = repair_agent.apply_pending_patch(confirmed=True)
                applied_files.extend(repaired_files)
                self._clear_pending_patch_file()
                self._record(
                    prepared.session_id,
                    "patch_applied",
                    {"repair_attempt": repair_attempts, "files": repaired_files},
                )
                test_result = self._run_tests(repair_agent)
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
                self._run_hooks(
                    session,
                    "post_test",
                    {
                        "task": prepared.task,
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

    def _run_hooks(self, session: AgentSession, event: str, payload: dict[str, Any]) -> None:
        runner = HookRunner(self.workspace.root_path, permission_mode=self.permission_mode)
        for result in runner.run_event(event, session_id=session.session_id, payload=payload):
            event_payload = result.to_event_payload()
            session.record("hook_result", event_payload)
            self._record(session.session_id, "hook_result", event_payload)
            if result.hook.required and not result.ok:
                raise PermissionDenied(f"required hook failed: {result.hook.id}: {result.output}")

    def _clear_pending_patch_file(self) -> None:
        patch_path = self.workspace.root_path / SESSION_DIR_NAME / PENDING_PATCH_FILE
        patch_path.unlink(missing_ok=True)

    def _review_patch(self, session: AgentSession, patch: str, coding_model_id: str) -> str | None:
        if self.review_provider is None or self.review_model_id is None:
            return None
        selection = self._select_model(
            session=session,
            role="review",
            task_type=TASK_REVIEW,
            task=patch,
            fallback_model_id=self.review_model_id,
            default_provider=self.review_provider,
            prefer_different_from=coding_model_id,
        )
        review_provider = self._provider_for(selection, self.review_provider)
        review = Reviewer(review_provider, selection.model_id).review_patch(patch)
        self._record_model_call(session, selection, review)
        self._record(session.session_id, "patch_reviewed", {"content": review.content})
        return review.content

    def _session_from_state(self, state: AgentState, task: str) -> AgentSession:
        return AgentSession(
            session_id=state.session_id,
            workspace_path=state.workspace_path,
            user_task=task,
            created_at=state.created_at,
        )

    def _select_model(
        self,
        *,
        session: AgentSession,
        role: str,
        task_type: str,
        task: str,
        fallback_model_id: str,
        default_provider: ProviderAdapter,
        prefer_different_from: str | None = None,
    ) -> ModelSelection:
        if self.runtime is None:
            return ModelSelection(
                model_id=fallback_model_id,
                role=role,
                task_type=task_type,
                reason=f"fixed role mapping for {role}",
                routing_mode="fixed",
            )
        return self.runtime.select_model(
            session=session,
            role=role,
            task_type=task_type,
            task=task,
            fallback_model_id=fallback_model_id,
            prefer_different_from=prefer_different_from,
        )

    def _provider_for(
        self,
        selection: ModelSelection,
        default_provider: ProviderAdapter,
    ) -> ProviderAdapter:
        if self.runtime is None:
            return default_provider
        return self.runtime.provider_for_model(selection.model_id, default_provider)

    def _record_model_call(
        self,
        session: AgentSession,
        selection: ModelSelection,
        response: ModelResponse | None = None,
    ) -> None:
        if self.runtime is not None:
            self.runtime.record_model_call(session, selection, response)

    def _allocate_task(self, session: AgentSession, task: str) -> TaskAllocation | None:
        if self.runtime is not None:
            return self.runtime.allocate_task(
                session=session,
                task=task,
                include_repair=self.allocation_include_repair,
                block_on_required=self.block_on_allocation,
                max_cost_score=self.max_cost_score,
                session_budget_score=self.session_budget_score,
                budget_key=self.budget_key,
            )
        return None

    def _run_preplan_agents(
        self,
        session: AgentSession,
        task: str,
        allocation: TaskAllocation | None,
    ) -> str | None:
        if allocation is None:
            return None
        assignments = [
            assignment
            for assignment in allocation.assignments
            if assignment.task_type in {TASK_REPO_SCAN, TASK_SUMMARIZE}
        ]
        if not assignments:
            return None
        base_context = ContextBuilder(self.workspace).build_for_task(task).text
        cache = PreplanCache(self.workspace.root_path) if self.preplan_cache_enabled else None
        outputs: list[str] = []
        for assignment in assignments:
            try:
                selection = self._select_model(
                    session=session,
                    role=assignment.role,
                    task_type=assignment.task_type,
                    task=task,
                    fallback_model_id=assignment.model_id,
                    default_provider=self.provider,
                )
            except ModelError as exc:
                self._record(
                    session.session_id,
                    "preplan_agent_skipped",
                    {"agent_id": assignment.agent_id, "reason": str(exc)},
                )
                continue
            if selection.quota_status is not None and not selection.quota_status.available:
                self._record(
                    session.session_id,
                    "preplan_agent_skipped",
                    {
                        "agent_id": assignment.agent_id,
                        "model_id": selection.model_id,
                        "reason": "quota unavailable",
                    },
                )
                continue
            provider = self._provider_for(selection, self.provider)
            cache_key = None
            if cache is not None:
                cache_key = cache.key_for(
                    agent_id=assignment.agent_id,
                    task_type=assignment.task_type,
                    model_id=selection.model_id,
                    task=task,
                    base_context=base_context,
                    previous_outputs=outputs,
                )
                cached = cache.get(cache_key)
                if cached is not None:
                    payload = {
                        "agent_id": assignment.agent_id,
                        "task_type": assignment.task_type,
                        "model_id": selection.model_id,
                        "cache_key": cache_key,
                        "content": cached.content,
                    }
                    session.record("preplan_agent_cache_hit", payload)
                    self._record(session.session_id, "preplan_agent_cache_hit", payload)
                    outputs.append(f"{assignment.agent_id} ({selection.model_id}):\n{cached.content}")
                    continue
            response = provider.chat(
                selection.model_id,
                self._preplan_messages(
                    assignment=assignment,
                    task=task,
                    base_context=base_context,
                    previous_outputs=outputs,
                ),
            )
            self._record_model_call(session, selection, response)
            payload = {
                "agent_id": assignment.agent_id,
                "task_type": assignment.task_type,
                "model_id": selection.model_id,
                "content": response.content,
            }
            session.record("preplan_agent_completed", payload)
            self._record(session.session_id, "preplan_agent_completed", payload)
            if cache is not None and cache_key is not None:
                cache.put(
                    key=cache_key,
                    agent_id=assignment.agent_id,
                    task_type=assignment.task_type,
                    model_id=selection.model_id,
                    content=response.content,
                )
            outputs.append(f"{assignment.agent_id} ({selection.model_id}):\n{response.content}")
        if not outputs:
            return None
        return "\n\n".join(outputs)

    def _preplan_messages(
        self,
        *,
        assignment: AgentAssignment,
        task: str,
        base_context: str,
        previous_outputs: list[str],
    ) -> list[ChatMessage]:
        if assignment.task_type == TASK_REPO_SCAN:
            system = (
                "You are helmcode's scout agent. Use only the provided repository context. "
                "Return concise bullets naming relevant files, likely change areas, and unknowns. "
                "Do not propose a patch."
            )
        else:
            system = (
                "You are helmcode's summarizer agent. Compress the repository context and prior "
                "agent findings into a concise implementation brief for the planning model. "
                "Keep file names, constraints, risks, and verification hints. Do not propose a patch."
            )
        prior = "\n\n".join(previous_outputs) if previous_outputs else "None"
        user = (
            f"Task:\n{task}\n\n"
            f"Repository context:\n{base_context}\n\n"
            f"Prior pre-agent findings:\n{prior}"
        )
        return [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]
