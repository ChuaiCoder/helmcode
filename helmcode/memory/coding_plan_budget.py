from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from helmcode.agent.allocation import TaskAllocation
from helmcode.core.constants import SESSION_DIR_NAME

BUDGET_FILE_NAME = "coding_plan_budget.json"
DEFAULT_BUDGET_KEY = "default"
BUDGET_WARNING_NUMERATOR = 4
BUDGET_WARNING_DENOMINATOR = 5


@dataclass(slots=True)
class CodingPlanBudgetStatus:
    key: str
    allocation_count: int = 0
    baseline_cost_score: int = 0
    selected_cost_score: int = 0
    estimated_savings_score: int = 0
    blocked_count: int = 0
    updated_at: str | None = None

    def remaining(self, max_score: int | None = None) -> int | None:
        if max_score is None:
            return None
        return max(max_score - self.selected_cost_score, 0)

    def would_exceed(self, allocation: TaskAllocation, max_score: int) -> bool:
        return self.selected_cost_score + allocation.selected_cost_score > max_score

    def warning_threshold(self, max_score: int | None = None) -> int | None:
        if max_score is None:
            return None
        return max(
            (max_score * BUDGET_WARNING_NUMERATOR + BUDGET_WARNING_DENOMINATOR - 1)
            // BUDGET_WARNING_DENOMINATOR,
            1,
        )

    def budget_warning(self, max_score: int | None = None) -> bool:
        threshold = self.warning_threshold(max_score)
        return threshold is not None and self.selected_cost_score >= threshold

    def to_dict(self, max_score: int | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "key": self.key,
            "allocation_count": self.allocation_count,
            "baseline_cost_score": self.baseline_cost_score,
            "selected_cost_score": self.selected_cost_score,
            "estimated_savings_score": self.estimated_savings_score,
            "blocked_count": self.blocked_count,
            "updated_at": self.updated_at,
        }
        if max_score is not None:
            payload["max_score"] = max_score
            payload["remaining_score"] = self.remaining(max_score)
            payload["warning_threshold_score"] = self.warning_threshold(max_score)
            payload["budget_warning"] = self.budget_warning(max_score)
        return payload


@dataclass(slots=True)
class CodingPlanBudgetDecision:
    allowed: bool
    status: CodingPlanBudgetStatus
    projected_selected_cost_score: int
    max_score: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "status": self.status.to_dict(max_score=self.max_score),
            "projected_selected_cost_score": self.projected_selected_cost_score,
            "max_score": self.max_score,
            "reason": self.reason,
        }


class CodingPlanBudgetLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_workspace(cls, workspace_path: Path) -> "CodingPlanBudgetLedger":
        return cls(workspace_path / SESSION_DIR_NAME / BUDGET_FILE_NAME)

    def status(self, key: str = DEFAULT_BUDGET_KEY) -> CodingPlanBudgetStatus:
        budgets = self._read_budgets()
        return _status_from_payload(key, budgets.get(key))

    def all_statuses(self) -> list[CodingPlanBudgetStatus]:
        budgets = self._read_budgets()
        return [_status_from_payload(key, value) for key, value in sorted(budgets.items())]

    def check(
        self,
        allocation: TaskAllocation,
        *,
        key: str = DEFAULT_BUDGET_KEY,
        max_score: int,
    ) -> CodingPlanBudgetDecision:
        status = self.status(key)
        projected = status.selected_cost_score + allocation.selected_cost_score
        allowed = projected <= max_score
        if allowed:
            reason = f"projected selected cost {projected} within session budget {max_score}"
        else:
            reason = f"projected selected cost {projected} exceeds session budget {max_score}"
        return CodingPlanBudgetDecision(
            allowed=allowed,
            status=status,
            projected_selected_cost_score=projected,
            max_score=max_score,
            reason=reason,
        )

    def record_allocation(
        self,
        allocation: TaskAllocation,
        *,
        key: str = DEFAULT_BUDGET_KEY,
    ) -> CodingPlanBudgetStatus:
        budgets = self._read_budgets()
        status = _status_from_payload(key, budgets.get(key))
        status.allocation_count += 1
        status.baseline_cost_score += allocation.baseline_cost_score
        status.selected_cost_score += allocation.selected_cost_score
        status.estimated_savings_score += allocation.estimated_savings_score
        status.updated_at = datetime.now(UTC).isoformat()
        budgets[key] = status.to_dict()
        self._write_budgets(budgets)
        return status

    def record_blocked(self, *, key: str = DEFAULT_BUDGET_KEY) -> CodingPlanBudgetStatus:
        budgets = self._read_budgets()
        status = _status_from_payload(key, budgets.get(key))
        status.blocked_count += 1
        status.updated_at = datetime.now(UTC).isoformat()
        budgets[key] = status.to_dict()
        self._write_budgets(budgets)
        return status

    def reset(self, key: str | None = None) -> int:
        budgets = self._read_budgets()
        if key is None:
            removed = len(budgets)
            self._write_budgets({})
            return removed
        if key not in budgets:
            return 0
        del budgets[key]
        self._write_budgets(budgets)
        return 1

    def _read_budgets(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        budgets = data.get("budgets") if isinstance(data, dict) else None
        if not isinstance(budgets, dict):
            return {}
        return {
            str(key): value
            for key, value in budgets.items()
            if isinstance(value, dict)
        }

    def _write_budgets(self, budgets: dict[str, dict[str, object]]) -> None:
        payload = {
            "version": 1,
            "budgets": budgets,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _status_from_payload(key: str, payload: dict[str, Any] | None) -> CodingPlanBudgetStatus:
    if payload is None:
        return CodingPlanBudgetStatus(key=key)
    return CodingPlanBudgetStatus(
        key=key,
        allocation_count=_int(payload.get("allocation_count")),
        baseline_cost_score=_int(payload.get("baseline_cost_score")),
        selected_cost_score=_int(payload.get("selected_cost_score")),
        estimated_savings_score=_int(payload.get("estimated_savings_score")),
        blocked_count=_int(payload.get("blocked_count")),
        updated_at=str(payload["updated_at"]) if payload.get("updated_at") else None,
    )


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
