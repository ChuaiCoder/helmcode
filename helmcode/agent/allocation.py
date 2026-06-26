from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from datetime import UTC, datetime

from helmcode.context.context_builder import estimate_explicit_reference_tokens
from helmcode.context.workspace import Workspace
from helmcode.core.config import AgentProfileConfig, HelmcodeConfig
from helmcode.core.constants import (
    MODEL_ROLE_CODING,
    MODEL_ROLE_FAST,
    MODEL_ROLE_PLANNING,
    MODEL_ROLE_REVIEW,
)
from helmcode.core.exceptions import ModelError
from helmcode.models.quota import (
    TASK_CODE_PATCH,
    TASK_PLAN,
    TASK_REPAIR,
    TASK_REPO_SCAN,
    TASK_REVIEW,
    TASK_SUMMARIZE,
    ModelCallRecord,
    ModelSelection,
    QuotaPolicyStatus,
    QuotaAwareSelector,
    classify_task,
)
from helmcode.models.selector import ModelSelector


COMPLEXITY_LOW = "low"
COMPLEXITY_MEDIUM = "medium"
COMPLEXITY_HIGH = "high"

TASK_TYPE_LABELS = {
    TASK_REPO_SCAN: "repository scan",
    TASK_SUMMARIZE: "summary",
    TASK_PLAN: "planning",
    TASK_CODE_PATCH: "coding",
    TASK_REPAIR: "repair",
    TASK_REVIEW: "review",
}

COST_SCORE = {"low": 1, "medium": 2, "high": 4}
DEFAULT_AGENT_TOKEN_ESTIMATE = 2_000


@dataclass(slots=True)
class AgentProfile:
    id: str
    role: str
    task_type: str
    model_role: str
    purpose: str
    order: int
    required: bool = True
    triggers: tuple[str, ...] = ()
    estimated_tokens: int = DEFAULT_AGENT_TOKEN_ESTIMATE


@dataclass(slots=True)
class AgentAssignment:
    agent_id: str
    role: str
    task_type: str
    purpose: str
    model_id: str
    reason: str
    required: bool
    estimated_cost_score: int
    model_cost_tier: str = "medium"
    quota_policy_id: str | None = None
    quota_unit: str | None = None
    quota_reserved_amount: int = 1
    quota_remaining: int | None = None
    quota_remaining_after: int | None = None
    quota_resets_at: str | None = None
    quota_reservations: list[dict[str, object]] | None = None
    context_token_estimate: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "task_type": self.task_type,
            "purpose": self.purpose,
            "model_id": self.model_id,
            "reason": self.reason,
            "required": self.required,
            "estimated_cost_score": self.estimated_cost_score,
            "model_cost_tier": self.model_cost_tier,
            "quota_policy_id": self.quota_policy_id,
            "quota_unit": self.quota_unit,
            "quota_reserved_amount": self.quota_reserved_amount,
            "quota_remaining": self.quota_remaining,
            "quota_remaining_after": self.quota_remaining_after,
            "quota_resets_at": self.quota_resets_at,
            "quota_reservations": self.quota_reservations or [],
            "context_token_estimate": self.context_token_estimate,
        }


@dataclass(slots=True)
class TaskAllocation:
    task: str
    detected_task_type: str
    complexity: str
    strategy: str
    assignments: list[AgentAssignment]
    warnings: list[str]
    estimated_calls: int
    baseline_calls: int
    baseline_model_id: str | None
    baseline_cost_score: int
    selected_cost_score: int
    max_cost_score: int | None = None

    @property
    def estimated_savings_score(self) -> int:
        return max(self.baseline_cost_score - self.selected_cost_score, 0)

    @property
    def blocked(self) -> bool:
        return any(warning.startswith("blocked:") for warning in self.warnings)

    @property
    def budget_exceeded(self) -> bool:
        return self.max_cost_score is not None and self.selected_cost_score > self.max_cost_score

    @property
    def required_cost_score(self) -> int:
        return sum(assignment.estimated_cost_score for assignment in self.assignments if assignment.required)

    @property
    def optional_cost_score(self) -> int:
        return sum(assignment.estimated_cost_score for assignment in self.assignments if not assignment.required)

    @property
    def selected_cost_by_tier(self) -> dict[str, int]:
        scores: dict[str, int] = {}
        for assignment in self.assignments:
            scores[assignment.model_cost_tier] = (
                scores.get(assignment.model_cost_tier, 0) + assignment.estimated_cost_score
            )
        return scores

    def cost_breakdown(self) -> dict[str, object]:
        return {
            "baseline": {
                "model_id": self.baseline_model_id,
                "calls": self.baseline_calls,
                "cost_score": self.baseline_cost_score,
            },
            "selected": {
                "calls": self.estimated_calls,
                "cost_score": self.selected_cost_score,
                "required_cost_score": self.required_cost_score,
                "optional_cost_score": self.optional_cost_score,
                "by_tier": self.selected_cost_by_tier,
            },
            "estimated_savings_score": self.estimated_savings_score,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "task": self.task,
            "detected_task_type": self.detected_task_type,
            "complexity": self.complexity,
            "strategy": self.strategy,
            "assignments": [assignment.to_dict() for assignment in self.assignments],
            "warnings": self.warnings,
            "blocked": self.blocked,
            "estimated_calls": self.estimated_calls,
            "baseline_calls": self.baseline_calls,
            "baseline_model_id": self.baseline_model_id,
            "baseline_cost_score": self.baseline_cost_score,
            "selected_cost_score": self.selected_cost_score,
            "max_cost_score": self.max_cost_score,
            "budget_exceeded": self.budget_exceeded,
            "estimated_savings_score": self.estimated_savings_score,
            "cost_breakdown": self.cost_breakdown(),
        }


DEFAULT_AGENT_PROFILES = [
    AgentProfile(
        id="scout",
        role="fast",
        task_type=TASK_REPO_SCAN,
        model_role=MODEL_ROLE_FAST,
        purpose="cheap repository discovery before spending coding quota",
        order=10,
        required=False,
        estimated_tokens=1_500,
    ),
    AgentProfile(
        id="summarizer",
        role="fast",
        task_type=TASK_SUMMARIZE,
        model_role=MODEL_ROLE_FAST,
        purpose="compress long task context before expensive calls",
        order=20,
        required=False,
        estimated_tokens=1_500,
    ),
    AgentProfile(
        id="planner",
        role="planning",
        task_type=TASK_PLAN,
        model_role=MODEL_ROLE_PLANNING,
        purpose="reason about implementation sequence and verification",
        order=30,
        required=True,
        estimated_tokens=2_500,
    ),
    AgentProfile(
        id="coder",
        role="coding",
        task_type=TASK_CODE_PATCH,
        model_role=MODEL_ROLE_CODING,
        purpose="produce the code patch",
        order=40,
        required=True,
        estimated_tokens=4_000,
    ),
    AgentProfile(
        id="reviewer",
        role="review",
        task_type=TASK_REVIEW,
        model_role=MODEL_ROLE_REVIEW,
        purpose="independent patch review with a different model when available",
        order=50,
        required=False,
        estimated_tokens=2_000,
    ),
    AgentProfile(
        id="fixer",
        role="coding",
        task_type=TASK_REPAIR,
        model_role=MODEL_ROLE_CODING,
        purpose="repair failed tests without re-running the full planning path",
        order=60,
        required=False,
        estimated_tokens=2_500,
    ),
]


class CodingPlanTaskAllocator:
    def __init__(
        self,
        config: HelmcodeConfig,
        selector: QuotaAwareSelector,
        workspace: Workspace | None = None,
    ) -> None:
        self.config = config
        self.selector = selector
        self.workspace = workspace
        self.role_selector = ModelSelector(config.model_roles)
        self.agent_profiles = _merge_agent_profiles(config.agent_profiles)
        self.model_profile_costs = {
            profile.id: COST_SCORE.get(profile.cost_tier, COST_SCORE["medium"])
            for profile in config.model_profiles
        }
        self.model_profile_tiers = {profile.id: profile.cost_tier for profile in config.model_profiles}
        self.explicit_context_token_estimate = 0

    def allocate(
        self,
        task: str,
        *,
        override_model_id: str | None = None,
        model_overrides: dict[str, str] | None = None,
        include_repair: bool = False,
        max_cost_score: int | None = None,
    ) -> TaskAllocation:
        detected_task_type = classify_task(task)
        complexity = classify_complexity(task)
        self.explicit_context_token_estimate = self._explicit_context_tokens(task)
        agent_ids = self._agent_ids_for_task(
            task=task,
            detected_task_type=detected_task_type,
            complexity=complexity,
            include_repair=include_repair,
        )
        triggered_agent_ids = self._triggered_agent_ids(task)
        agent_ids = self._merge_triggered_agent_ids(agent_ids, triggered_agent_ids)
        assignments: list[AgentAssignment] = []
        reservation_groups: list[list[ModelCallRecord]] = []
        warnings: list[str] = []
        coding_model: str | None = None

        for agent in self._ordered_agents(agent_ids, detected_task_type=detected_task_type):
            fallback_model_id = self._fallback_model(agent)
            scoped_override_model_id = (
                override_model_id or _model_override_for_agent(agent, model_overrides)
            )
            override_reason = (
                "explicit --model override"
                if override_model_id
                else _model_override_reason(agent, model_overrides)
            )
            while True:
                try:
                    selection = self.selector.select(
                        role=agent.role,
                        task_type=agent.task_type,
                        task=task,
                        fallback_model_id=fallback_model_id,
                        override_model_id=scoped_override_model_id,
                        override_reason=override_reason,
                        prefer_different_from=coding_model if agent.id == "reviewer" else None,
                        reserved_records=_flatten_reservations(reservation_groups),
                    )
                except ModelError as exc:
                    message = str(exc)
                    if (
                        agent.required
                        and _looks_like_capacity_issue(message)
                        and self._release_optional_reservation(
                            assignments,
                            reservation_groups,
                            warnings,
                            agent,
                            message,
                        )
                    ):
                        continue
                    if agent.required:
                        warnings.append(f"blocked:{agent.id}:{exc}")
                    else:
                        warnings.append(f"skipped:{agent.id}:{exc}")
                    break
                if selection.quota_status is not None and not self._selection_has_capacity_for(agent, selection):
                    message = self._quota_unavailable_message(agent, selection)
                    if (
                        agent.required
                        and _looks_like_capacity_issue(message)
                        and self._release_optional_reservation(
                            assignments,
                            reservation_groups,
                            warnings,
                            agent,
                            message,
                            selection=selection,
                        )
                    ):
                        continue
                    if agent.required:
                        warnings.append(f"blocked:{agent.id}:{message}")
                    else:
                        warnings.append(f"skipped:{agent.id}:{message}")
                    break
                if (
                    scoped_override_model_id is None
                    and not self._model_can_handle(selection.model_id, agent, fallback_model_id)
                ):
                    message = (
                        f"{selection.model_id} is not profiled for {agent.task_type}; "
                        f"refusing unsafe fallback for {agent.id}"
                    )
                    if agent.required:
                        warnings.append(f"blocked:{agent.id}:{message}")
                    else:
                        warnings.append(f"skipped:{agent.id}:{message}")
                    break
                if agent.id == "coder":
                    coding_model = selection.model_id
                assignment = self._assignment(agent, selection)
                assignments.append(assignment)
                reservation_groups.append(self._reservations_for(agent, selection))
                break

        baseline_model_id = self._baseline_model()
        baseline_cost = self._baseline_cost(agent_ids, baseline_model_id)
        assignments = self._apply_budget_cap(assignments, warnings, max_cost_score)
        selected_cost = sum(assignment.estimated_cost_score for assignment in assignments)
        return TaskAllocation(
            task=task,
            detected_task_type=detected_task_type,
            complexity=complexity,
            strategy=self._strategy(detected_task_type, complexity),
            assignments=assignments,
            warnings=warnings,
            estimated_calls=len(assignments),
            baseline_calls=len(agent_ids),
            baseline_model_id=baseline_model_id,
            baseline_cost_score=baseline_cost,
            selected_cost_score=selected_cost,
            max_cost_score=max_cost_score,
        )

    def _agent_ids_for_task(
        self,
        *,
        task: str,
        detected_task_type: str,
        complexity: str,
        include_repair: bool,
    ) -> list[str]:
        if detected_task_type == TASK_REVIEW:
            return ["reviewer"]
        if detected_task_type == TASK_REPAIR:
            return ["scout", "fixer", "reviewer"] if complexity != COMPLEXITY_LOW else ["fixer"]
        if detected_task_type == TASK_PLAN:
            return ["scout", "planner"] if complexity != COMPLEXITY_LOW else ["planner"]
        if detected_task_type == TASK_SUMMARIZE:
            return ["summarizer"]
        if detected_task_type == TASK_REPO_SCAN:
            return ["scout"]

        agents = ["planner", "coder"]
        if complexity in {COMPLEXITY_MEDIUM, COMPLEXITY_HIGH}:
            agents.insert(0, "scout")
        if _looks_context_heavy(task):
            agents.insert(1, "summarizer")
        if complexity != COMPLEXITY_LOW:
            agents.append("reviewer")
        if include_repair:
            agents.append("fixer")
        return _dedupe(agents)

    def _ordered_agents(self, agent_ids: list[str], *, detected_task_type: str) -> list[AgentProfile]:
        selected = [profile for profile in self.agent_profiles if profile.id in agent_ids]
        if detected_task_type == TASK_REPAIR:
            order_by_id = {agent_id: index for index, agent_id in enumerate(agent_ids)}
            return sorted(selected, key=lambda profile: (order_by_id.get(profile.id, len(agent_ids)), profile.id))
        return sorted(selected, key=lambda profile: (profile.order, profile.id))

    def _triggered_agent_ids(self, task: str) -> list[str]:
        lowered = task.lower()
        return [
            profile.id
            for profile in self.agent_profiles
            if profile.triggers and any(trigger.lower() in lowered for trigger in profile.triggers)
        ]

    def _merge_triggered_agent_ids(self, base_agent_ids: list[str], triggered_agent_ids: list[str]) -> list[str]:
        if not triggered_agent_ids:
            return _dedupe(base_agent_ids)
        profiles_by_id = {profile.id: profile for profile in self.agent_profiles}
        triggered_task_types = {
            profiles_by_id[agent_id].task_type
            for agent_id in triggered_agent_ids
            if agent_id in profiles_by_id
        }
        merged: list[str] = []
        for agent_id in base_agent_ids:
            profile = profiles_by_id.get(agent_id)
            if (
                profile is not None
                and not profile.required
                and profile.task_type in triggered_task_types
                and agent_id not in triggered_agent_ids
            ):
                continue
            merged.append(agent_id)
        return _dedupe([*merged, *triggered_agent_ids])

    def _fallback_model(self, agent: AgentProfile) -> str:
        return self.config.model_roles.get(agent.model_role) or self.role_selector.select(agent.role)

    def _assignment(self, agent: AgentProfile, selection: ModelSelection) -> AgentAssignment:
        quota_status = selection.quota_status
        quota_reservations = self._quota_reservation_details(agent, selection)
        primary_quota = quota_reservations[0] if quota_reservations else None
        return AgentAssignment(
            agent_id=agent.id,
            role=agent.role,
            task_type=agent.task_type,
            purpose=agent.purpose,
            model_id=selection.model_id,
            reason=selection.reason,
            required=agent.required,
            estimated_cost_score=self._cost_for_model(selection.model_id),
            model_cost_tier=self._tier_for_model(selection.model_id),
            quota_policy_id=str(primary_quota["policy_id"]) if primary_quota else None,
            quota_unit=str(primary_quota["unit"]) if primary_quota else (quota_status.unit if quota_status else None),
            quota_reserved_amount=int(primary_quota["reserved_amount"]) if primary_quota else 1,
            quota_remaining=(
                int(primary_quota["remaining"])
                if primary_quota and primary_quota["remaining"] is not None
                else None
            ),
            quota_remaining_after=(
                int(primary_quota["remaining_after"])
                if primary_quota and primary_quota["remaining_after"] is not None
                else None
            ),
            quota_resets_at=str(primary_quota["resets_at"]) if primary_quota and primary_quota["resets_at"] else None,
            quota_reservations=quota_reservations,
            context_token_estimate=self._context_token_estimate_for(agent),
        )

    def _apply_budget_cap(
        self,
        assignments: list[AgentAssignment],
        warnings: list[str],
        max_cost_score: int | None,
    ) -> list[AgentAssignment]:
        if max_cost_score is None:
            return assignments
        selected_cost = sum(assignment.estimated_cost_score for assignment in assignments)
        if selected_cost <= max_cost_score:
            return assignments
        kept = list(assignments)
        profiles_by_id = {profile.id: profile for profile in self.agent_profiles}
        removable = sorted(
            [assignment for assignment in kept if not assignment.required],
            key=lambda assignment: (
                assignment.estimated_cost_score,
                profiles_by_id[assignment.agent_id].order if assignment.agent_id in profiles_by_id else 0,
            ),
            reverse=True,
        )
        for assignment in removable:
            if selected_cost <= max_cost_score:
                break
            kept.remove(assignment)
            selected_cost -= assignment.estimated_cost_score
            warnings.append(
                f"skipped:{assignment.agent_id}:budget cap {max_cost_score} "
                f"removed optional agent costing {assignment.estimated_cost_score}"
            )
        return kept

    def _release_optional_reservation(
        self,
        assignments: list[AgentAssignment],
        reservation_groups: list[list[ModelCallRecord]],
        warnings: list[str],
        required_agent: AgentProfile,
        reason: str,
        selection: ModelSelection | None = None,
    ) -> bool:
        for index in range(len(assignments) - 1, -1, -1):
            assignment = assignments[index]
            if assignment.required:
                continue
            if selection is not None and not any(
                self._reservation_affects_selection(reservation, selection)
                for reservation in reservation_groups[index]
            ):
                continue
            assignments.pop(index)
            reservation_groups.pop(index)
            warnings.append(
                f"skipped:{assignment.agent_id}:released optional reservation for required "
                f"{required_agent.id}: {reason}"
            )
            return True
        return False

    def _reservation_affects_selection(self, reservation: ModelCallRecord, selection: ModelSelection) -> bool:
        status = selection.quota_status
        if status is None or not status.metered:
            return reservation.model_id == selection.model_id
        if reservation.unit not in status.metered_units:
            return False
        policy_ids = {
            policy_status.policy_id
            for policy_status in status.policy_statuses
            if policy_status.unit == reservation.unit
        }
        policies = [policy for policy in self.config.quota_policies if policy.id in policy_ids]
        if not policies:
            return reservation.model_id == selection.model_id
        return any(
            fnmatch.fnmatch(reservation.model_id, pattern)
            for policy in policies
            for pattern in policy.model_patterns
        )

    def _reservations_for(self, agent: AgentProfile, selection: ModelSelection) -> list[ModelCallRecord]:
        status = selection.quota_status
        units = status.metered_units if status and status.metered else ["request"]
        return [
            ModelCallRecord(
                timestamp=datetime.now(UTC),
                model_id=selection.model_id,
                role=agent.role,
                task_type=agent.task_type,
                unit=unit,
                amount=self._reservation_amount_for_unit(agent, unit),
                reason=f"allocation reservation:{agent.id}",
            )
            for unit in units
        ]

    def _selection_has_capacity_for(self, agent: AgentProfile, selection: ModelSelection) -> bool:
        status = selection.quota_status
        if status is None:
            return True
        for policy_status in _quota_policy_statuses(status):
            if not policy_status.available:
                return False
            remaining = policy_status.tightest_remaining
            if remaining is not None and remaining < self._reservation_amount_for_unit(agent, policy_status.unit):
                return False
        return True

    def _reservation_amount(self, agent: AgentProfile, selection: ModelSelection) -> int:
        policy_statuses = _quota_policy_statuses(selection.quota_status)
        if policy_statuses:
            return self._reservation_amount_for_unit(agent, policy_statuses[0].unit)
        status = selection.quota_status
        if status is not None:
            return self._reservation_amount_for_unit(agent, status.unit)
        return 1

    def _reservation_amount_for_unit(self, agent: AgentProfile, unit: str) -> int:
        if unit == "token":
            return max(agent.estimated_tokens + self._context_token_estimate_for(agent), 1)
        return 1

    def _baseline_model(self) -> str | None:
        return self.config.model_roles.get(MODEL_ROLE_CODING) or self.config.model_roles.get("default")

    def _baseline_cost(self, agent_ids: list[str], baseline_model_id: str | None) -> int:
        coding_cost = self._cost_for_model(baseline_model_id) if baseline_model_id else COST_SCORE["high"]
        return len(agent_ids) * coding_cost

    def _cost_for_model(self, model_id: str) -> int:
        return self.model_profile_costs.get(model_id, COST_SCORE["medium"])

    def _tier_for_model(self, model_id: str) -> str:
        return self.model_profile_tiers.get(model_id, "medium")

    def _model_can_handle(self, model_id: str, agent: AgentProfile, fallback_model_id: str) -> bool:
        if model_id == fallback_model_id:
            return True
        profile = next((profile for profile in self.config.model_profiles if profile.id == model_id), None)
        if profile is None:
            return False
        return agent.task_type in profile.preferred_for

    def _quota_unavailable_message(self, agent: AgentProfile, selection: ModelSelection) -> str:
        status = selection.quota_status
        if status is None:
            return f"{selection.model_id} has no quota capacity"
        for policy_status in _quota_policy_statuses(status):
            required_amount = self._reservation_amount_for_unit(agent, policy_status.unit)
            remaining = policy_status.tightest_remaining
            if policy_status.available and remaining is not None and remaining < required_amount:
                return (
                    f"{selection.model_id} has insufficient quota capacity under {policy_status.policy_id}; "
                    f"needs estimated {required_amount} {policy_status.unit}, remaining {remaining}"
                )
            if not policy_status.available:
                reset_text = (
                    policy_status.next_restore_at.isoformat()
                    if policy_status.next_restore_at
                    else "unknown reset time"
                )
                return (
                    f"{selection.model_id} has no quota capacity under "
                    f"{policy_status.policy_id}; resets at {reset_text}"
                )
        reset_text = status.next_restore_at.isoformat() if status.next_restore_at else "unknown reset time"
        policy_text = status.policy_id or "unscoped quota policy"
        return f"{selection.model_id} has no quota capacity under {policy_text}; resets at {reset_text}"

    def _quota_reservation_details(self, agent: AgentProfile, selection: ModelSelection) -> list[dict[str, object]]:
        status = selection.quota_status
        if status is None:
            return []
        details: list[dict[str, object]] = []
        for policy_status in _quota_policy_statuses(status):
            reserved_amount = self._reservation_amount_for_unit(agent, policy_status.unit)
            remaining = policy_status.tightest_remaining
            details.append(
                {
                    "policy_id": policy_status.policy_id,
                    "unit": policy_status.unit,
                    "reserved_amount": reserved_amount,
                    "remaining": remaining,
                    "remaining_after": _remaining_after_reservation(remaining, reserved_amount),
                    "context_token_estimate": self._context_token_estimate_for(agent),
                    "resets_at": (
                        policy_status.next_restore_at.isoformat()
                        if policy_status.next_restore_at
                        else None
                    ),
                }
            )
        return details

    def _explicit_context_tokens(self, task: str) -> int:
        if self.workspace is None:
            return 0
        return estimate_explicit_reference_tokens(self.workspace, task)

    def _context_token_estimate_for(self, agent: AgentProfile) -> int:
        if agent.task_type == TASK_REVIEW:
            return 0
        return self.explicit_context_token_estimate

    def _strategy(self, task_type: str, complexity: str) -> str:
        if task_type in {TASK_REPO_SCAN, TASK_SUMMARIZE, TASK_REVIEW}:
            return f"single-agent {TASK_TYPE_LABELS.get(task_type, task_type)}"
        if task_type == TASK_PLAN:
            if complexity == COMPLEXITY_LOW:
                return "single-agent planning"
            return "scout-planning path with cheap repository discovery"
        if task_type == TASK_REPAIR:
            if complexity == COMPLEXITY_LOW:
                return "single-agent repair"
            return "scout-repair-review path"
        if complexity == COMPLEXITY_LOW:
            return "quota-saving direct path"
        if complexity == COMPLEXITY_MEDIUM:
            return "scout-plan-code with selective review"
        return "full multi-agent path with cheap context preparation"


def classify_complexity(task: str) -> str:
    lowered = task.lower()
    score = 0
    if len(task) > 120:
        score += 1
    if len(task) > 260:
        score += 1
    for token in [
        "architecture",
        "refactor",
        "migration",
        "database",
        "security",
        "performance",
        "concurrent",
        "multi-agent",
        "multiagent",
        "failing tests",
        "whole project",
        "\u67b6\u6784",
        "\u91cd\u6784",
        "\u8fc1\u79fb",
        "\u6027\u80fd",
        "\u5b89\u5168",
        "\u6574\u4e2a\u9879\u76ee",
        "\u591aagent",
    ]:
        if token in lowered:
            score += 1
    if score >= 2:
        return COMPLEXITY_HIGH
    if score == 1:
        return COMPLEXITY_MEDIUM
    return COMPLEXITY_LOW


def _merge_agent_profiles(configured: list[AgentProfileConfig]) -> list[AgentProfile]:
    profiles = {profile.id: profile for profile in DEFAULT_AGENT_PROFILES}
    for item in configured:
        existing = profiles.get(item.id)
        if item.estimated_tokens is not None:
            estimated_tokens = item.estimated_tokens
        elif existing is not None:
            estimated_tokens = existing.estimated_tokens
        else:
            estimated_tokens = DEFAULT_AGENT_TOKEN_ESTIMATE
        profiles[item.id] = AgentProfile(
            id=item.id,
            role=item.role,
            task_type=item.task_type,
            model_role=item.model_role,
            purpose=item.purpose,
            order=item.order,
            required=item.required,
            triggers=tuple(item.triggers),
            estimated_tokens=estimated_tokens,
        )
    return list(profiles.values())


def _looks_context_heavy(task: str) -> bool:
    lowered = task.lower()
    return any(
        token in lowered
        for token in [
            "large",
            "long",
            "entire",
            "whole",
            "compress",
            "summary",
            "\u5927\u578b",
            "\u5f88\u957f",
            "\u6574\u4e2a",
            "\u538b\u7f29",
            "\u603b\u7ed3",
        ]
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _model_override_for_agent(
    agent: AgentProfile,
    model_overrides: dict[str, str] | None,
) -> str | None:
    if not model_overrides:
        return None
    overrides = {key.lower(): value for key, value in model_overrides.items()}
    for key in _model_override_keys(agent):
        model_id = overrides.get(key)
        if model_id:
            return model_id
    return None


def _model_override_reason(
    agent: AgentProfile,
    model_overrides: dict[str, str] | None,
) -> str | None:
    if not model_overrides:
        return None
    overrides = {key.lower(): value for key, value in model_overrides.items()}
    for key in _model_override_keys(agent):
        if overrides.get(key):
            return f"explicit model override for {key}"
    return None


def _model_override_keys(agent: AgentProfile) -> tuple[str, ...]:
    return (
        agent.id.lower(),
        agent.role.lower(),
        agent.model_role.lower(),
        agent.task_type.lower(),
    )


def _remaining_after_reservation(remaining: int | None, amount: int = 1) -> int | None:
    if remaining is None:
        return None
    return max(remaining - amount, 0)


def _quota_policy_statuses(status) -> list[QuotaPolicyStatus]:
    if status is None:
        return []
    return list(status.policy_statuses)


def _flatten_reservations(reservation_groups: list[list[ModelCallRecord]]) -> list[ModelCallRecord]:
    return [reservation for group in reservation_groups for reservation in group]


def _looks_like_capacity_issue(message: str) -> bool:
    lowered = message.lower()
    return "quota" in lowered or "capacity" in lowered
