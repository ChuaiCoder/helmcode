from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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
    quota_policy_id: str | None = None
    quota_remaining: int | None = None
    quota_remaining_after: int | None = None
    quota_resets_at: str | None = None

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
            "quota_policy_id": self.quota_policy_id,
            "quota_remaining": self.quota_remaining,
            "quota_remaining_after": self.quota_remaining_after,
            "quota_resets_at": self.quota_resets_at,
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
    baseline_cost_score: int
    selected_cost_score: int

    @property
    def estimated_savings_score(self) -> int:
        return max(self.baseline_cost_score - self.selected_cost_score, 0)

    @property
    def blocked(self) -> bool:
        return any(warning.startswith("blocked:") for warning in self.warnings)

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
            "baseline_cost_score": self.baseline_cost_score,
            "selected_cost_score": self.selected_cost_score,
            "estimated_savings_score": self.estimated_savings_score,
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
    ),
    AgentProfile(
        id="summarizer",
        role="fast",
        task_type=TASK_SUMMARIZE,
        model_role=MODEL_ROLE_FAST,
        purpose="compress long task context before expensive calls",
        order=20,
        required=False,
    ),
    AgentProfile(
        id="planner",
        role="planning",
        task_type=TASK_PLAN,
        model_role=MODEL_ROLE_PLANNING,
        purpose="reason about implementation sequence and verification",
        order=30,
        required=True,
    ),
    AgentProfile(
        id="coder",
        role="coding",
        task_type=TASK_CODE_PATCH,
        model_role=MODEL_ROLE_CODING,
        purpose="produce the code patch",
        order=40,
        required=True,
    ),
    AgentProfile(
        id="reviewer",
        role="review",
        task_type=TASK_REVIEW,
        model_role=MODEL_ROLE_REVIEW,
        purpose="independent patch review with a different model when available",
        order=50,
        required=False,
    ),
    AgentProfile(
        id="fixer",
        role="coding",
        task_type=TASK_REPAIR,
        model_role=MODEL_ROLE_CODING,
        purpose="repair failed tests without re-running the full planning path",
        order=60,
        required=False,
    ),
]


class CodingPlanTaskAllocator:
    def __init__(self, config: HelmcodeConfig, selector: QuotaAwareSelector) -> None:
        self.config = config
        self.selector = selector
        self.role_selector = ModelSelector(config.model_roles)
        self.agent_profiles = _merge_agent_profiles(config.agent_profiles)
        self.model_profile_costs = {
            profile.id: COST_SCORE.get(profile.cost_tier, COST_SCORE["medium"])
            for profile in config.model_profiles
        }

    def allocate(
        self,
        task: str,
        *,
        override_model_id: str | None = None,
        include_repair: bool = False,
    ) -> TaskAllocation:
        detected_task_type = classify_task(task)
        complexity = classify_complexity(task)
        agent_ids = self._agent_ids_for_task(
            task=task,
            detected_task_type=detected_task_type,
            complexity=complexity,
            include_repair=include_repair,
        )
        triggered_agent_ids = self._triggered_agent_ids(task)
        agent_ids = self._merge_triggered_agent_ids(agent_ids, triggered_agent_ids)
        assignments: list[AgentAssignment] = []
        warnings: list[str] = []
        coding_model: str | None = None
        reserved_records: list[ModelCallRecord] = []

        for agent in self._ordered_agents(agent_ids):
            fallback_model_id = self._fallback_model(agent)
            try:
                selection = self.selector.select(
                    role=agent.role,
                    task_type=agent.task_type,
                    task=task,
                    fallback_model_id=fallback_model_id,
                    override_model_id=override_model_id,
                    prefer_different_from=coding_model if agent.id == "reviewer" else None,
                    reserved_records=reserved_records,
                )
            except ModelError as exc:
                if agent.required:
                    warnings.append(f"blocked:{agent.id}:{exc}")
                else:
                    warnings.append(f"skipped:{agent.id}:{exc}")
                continue
            if selection.quota_status is not None and not selection.quota_status.available:
                message = self._quota_unavailable_message(selection)
                if agent.required:
                    warnings.append(f"blocked:{agent.id}:{message}")
                else:
                    warnings.append(f"skipped:{agent.id}:{message}")
                continue
            if override_model_id is None and not self._model_can_handle(selection.model_id, agent, fallback_model_id):
                message = (
                    f"{selection.model_id} is not profiled for {agent.task_type}; "
                    f"refusing unsafe fallback for {agent.id}"
                )
                if agent.required:
                    warnings.append(f"blocked:{agent.id}:{message}")
                else:
                    warnings.append(f"skipped:{agent.id}:{message}")
                continue
            if agent.id == "coder":
                coding_model = selection.model_id
            assignments.append(self._assignment(agent, selection))
            reserved_records.append(self._reservation_for(agent, selection))

        baseline_cost = self._baseline_cost(agent_ids)
        selected_cost = sum(assignment.estimated_cost_score for assignment in assignments)
        return TaskAllocation(
            task=task,
            detected_task_type=detected_task_type,
            complexity=complexity,
            strategy=self._strategy(detected_task_type, complexity),
            assignments=assignments,
            warnings=warnings,
            estimated_calls=len(assignments),
            baseline_cost_score=baseline_cost,
            selected_cost_score=selected_cost,
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

    def _ordered_agents(self, agent_ids: list[str]) -> list[AgentProfile]:
        selected = [profile for profile in self.agent_profiles if profile.id in agent_ids]
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
        resets_at = quota_status.next_restore_at.isoformat() if quota_status and quota_status.next_restore_at else None
        return AgentAssignment(
            agent_id=agent.id,
            role=agent.role,
            task_type=agent.task_type,
            purpose=agent.purpose,
            model_id=selection.model_id,
            reason=selection.reason,
            required=agent.required,
            estimated_cost_score=self._cost_for_model(selection.model_id),
            quota_policy_id=quota_status.policy_id if quota_status else None,
            quota_remaining=quota_status.tightest_remaining if quota_status else None,
            quota_remaining_after=_remaining_after_reservation(
                quota_status.tightest_remaining if quota_status else None
            ),
            quota_resets_at=resets_at,
        )

    def _reservation_for(self, agent: AgentProfile, selection: ModelSelection) -> ModelCallRecord:
        unit = selection.quota_status.unit if selection.quota_status else "request"
        return ModelCallRecord(
            timestamp=datetime.now(UTC),
            model_id=selection.model_id,
            role=agent.role,
            task_type=agent.task_type,
            unit=unit,
            reason="allocation reservation",
        )

    def _baseline_cost(self, agent_ids: list[str]) -> int:
        coding_model = self.config.model_roles.get(MODEL_ROLE_CODING) or self.config.model_roles.get("default")
        coding_cost = self._cost_for_model(coding_model) if coding_model else COST_SCORE["high"]
        return len(agent_ids) * coding_cost

    def _cost_for_model(self, model_id: str) -> int:
        return self.model_profile_costs.get(model_id, COST_SCORE["medium"])

    def _model_can_handle(self, model_id: str, agent: AgentProfile, fallback_model_id: str) -> bool:
        if model_id == fallback_model_id:
            return True
        profile = next((profile for profile in self.config.model_profiles if profile.id == model_id), None)
        if profile is None:
            return False
        return agent.task_type in profile.preferred_for

    def _quota_unavailable_message(self, selection: ModelSelection) -> str:
        status = selection.quota_status
        if status is None:
            return f"{selection.model_id} has no quota capacity"
        reset_text = status.next_restore_at.isoformat() if status.next_restore_at else "unknown reset time"
        policy_text = status.policy_id or "unscoped quota policy"
        return f"{selection.model_id} has no quota capacity under {policy_text}; resets at {reset_text}"

    def _strategy(self, task_type: str, complexity: str) -> str:
        if task_type in {TASK_REPO_SCAN, TASK_SUMMARIZE, TASK_REVIEW}:
            return f"single-agent {TASK_TYPE_LABELS.get(task_type, task_type)}"
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
        profiles[item.id] = AgentProfile(
            id=item.id,
            role=item.role,
            task_type=item.task_type,
            model_role=item.model_role,
            purpose=item.purpose,
            order=item.order,
            required=item.required,
            triggers=tuple(item.triggers),
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


def _remaining_after_reservation(remaining: int | None) -> int | None:
    if remaining is None:
        return None
    return max(remaining - 1, 0)
