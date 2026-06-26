from __future__ import annotations

from collections.abc import Callable

from helmcode.agent.allocation import CodingPlanTaskAllocator, TaskAllocation
from helmcode.agent.session import AgentSession
from helmcode.context.workspace import Workspace
from helmcode.core.exceptions import ModelError
from helmcode.memory.session_store import SessionStore
from helmcode.models.provider import ModelResponse, ProviderAdapter
from helmcode.models.quota import ModelSelection, QuotaAwareSelector


class AgentRuntime:
    """Runtime boundary for model routing, quota recording, and session events."""

    def __init__(
        self,
        workspace: Workspace,
        selector: QuotaAwareSelector | None = None,
        provider_resolver: Callable[[str], ProviderAdapter] | None = None,
        session_store: SessionStore | None = None,
        override_model_id: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.selector = selector
        self.provider_resolver = provider_resolver
        self.session_store = session_store
        self.override_model_id = override_model_id

    def allocate_task(
        self,
        *,
        session: AgentSession,
        task: str,
        include_repair: bool = False,
        block_on_required: bool = True,
        max_cost_score: int | None = None,
    ) -> TaskAllocation | None:
        if self.selector is None:
            return None
        allocation = CodingPlanTaskAllocator(
            self.selector.config,
            self.selector,
            workspace=self.workspace,
        ).allocate(
            task,
            override_model_id=self.override_model_id,
            include_repair=include_repair,
            max_cost_score=max_cost_score,
        )
        payload = allocation.to_dict()
        session.record("task_allocated", payload)
        self._record(session.session_id, "task_allocated", payload)
        if allocation.budget_exceeded:
            blocked_payload = {
                "selected_cost_score": allocation.selected_cost_score,
                "max_cost_score": allocation.max_cost_score,
                "estimated_savings_score": allocation.estimated_savings_score,
            }
            session.record("task_budget_blocked", blocked_payload)
            self._record(session.session_id, "task_budget_blocked", blocked_payload)
            raise ModelError(
                "Coding Plan budget exceeded: "
                f"selected cost score {allocation.selected_cost_score} > max {allocation.max_cost_score}"
            )
        if block_on_required and allocation.blocked:
            raise ModelError("Coding Plan allocation blocked: " + "; ".join(allocation.warnings))
        return allocation

    def select_model(
        self,
        *,
        session: AgentSession,
        role: str,
        task_type: str,
        task: str,
        fallback_model_id: str,
        prefer_different_from: str | None = None,
    ) -> ModelSelection:
        if self.selector is None:
            selection = ModelSelection(
                model_id=self.override_model_id or fallback_model_id,
                role=role,
                task_type=task_type,
                reason=f"fixed role mapping for {role}",
                routing_mode="fixed",
            )
        else:
            try:
                selection = self.selector.select(
                    role=role,
                    task_type=task_type,
                    task=task,
                    fallback_model_id=fallback_model_id,
                    override_model_id=self.override_model_id,
                    prefer_different_from=prefer_different_from,
                )
            except ModelError as exc:
                payload = {
                    "role": role,
                    "task_type": task_type,
                    "model_id": self.override_model_id or fallback_model_id,
                    "routing_mode": self.selector.routing_mode,
                    "reason": str(exc),
                    "blocked_reason": str(exc),
                }
                session.record("model_blocked", payload)
                self._record(session.session_id, "model_blocked", payload)
                raise
        if selection.quota_status is not None and not selection.quota_status.available:
            payload = {
                "role": role,
                "task_type": task_type,
                "model_id": selection.model_id,
                "routing_mode": selection.routing_mode,
                "reason": selection.reason,
                "blocked_reason": self._quota_unavailable_message(selection),
            }
            session.record("model_blocked", payload)
            self._record(session.session_id, "model_blocked", payload)
            raise ModelError(payload["blocked_reason"])
        payload = {
            "role": role,
            "task_type": task_type,
            "model_id": selection.model_id,
            "routing_mode": selection.routing_mode,
            "reason": selection.reason,
        }
        session.record("model_selected", payload)
        self._record(session.session_id, "model_selected", payload)
        return selection

    def provider_for_model(self, model_id: str, default_provider: ProviderAdapter) -> ProviderAdapter:
        if self.provider_resolver is None:
            return default_provider
        return self.provider_resolver(model_id)

    def record_model_call(
        self,
        session: AgentSession,
        selection: ModelSelection,
        response: ModelResponse | None = None,
    ) -> None:
        usage = response.usage if response is not None else {}
        payload = {
            "role": selection.role,
            "task_type": selection.task_type,
            "model_id": selection.model_id,
            "routing_mode": selection.routing_mode,
            "reason": selection.reason,
        }
        if usage:
            payload["usage"] = usage
        session.record("model_called", payload)
        self._record(session.session_id, "model_called", payload)
        if self.selector is not None:
            self.selector.record_call(
                selection,
                session_id=session.session_id,
                amounts_by_unit=_quota_amounts(selection, usage),
            )

    def _record(self, session_id: str, event_type: str, payload: dict[str, object]) -> None:
        if self.session_store is not None:
            self.session_store.record(session_id, event_type, payload)

    def _quota_unavailable_message(self, selection: ModelSelection) -> str:
        status = selection.quota_status
        if status is None:
            return f"No quota capacity for {selection.role}/{selection.task_type} on {selection.model_id}"
        reset_text = status.next_restore_at.isoformat() if status.next_restore_at else "unknown reset time"
        policy_text = status.policy_id or "unscoped quota policy"
        return (
            f"No quota capacity for {selection.role}/{selection.task_type} on "
            f"{selection.model_id} under {policy_text}; resets at {reset_text}"
        )


def _quota_amounts(selection: ModelSelection, usage: dict[str, int]) -> dict[str, int]:
    units = selection.quota_status.metered_units if selection.quota_status else []
    if not units:
        units = ["request"]
    amounts: dict[str, int] = {}
    for unit in units:
        if unit == "token":
            amounts[unit] = max(usage.get("total_tokens", 0), 1)
        else:
            amounts[unit] = 1
    return amounts
