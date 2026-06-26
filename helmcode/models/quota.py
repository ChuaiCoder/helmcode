from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from helmcode.core.config import HelmcodeConfig, ModelProfileConfig, QuotaPolicyConfig
from helmcode.core.constants import MODEL_ROLE_DEFAULT, SESSION_DIR_NAME
from helmcode.core.exceptions import ModelError
from helmcode.models.selector import ModelSelector


TASK_CLASSIFY = "classify"
TASK_REPO_SCAN = "repo_scan"
TASK_PLAN = "plan"
TASK_CODE_PATCH = "code_patch"
TASK_REPAIR = "repair"
TASK_REVIEW = "review"
TASK_SUMMARIZE = "summarize"

ROLE_TASK_TYPES = {
    "fast": TASK_CLASSIFY,
    "planning": TASK_PLAN,
    "coding": TASK_CODE_PATCH,
    "review": TASK_REVIEW,
}

COST_ORDER = {"low": 0, "medium": 1, "high": 2}
MODEL_PRESET_AUTO = "auto"
MODEL_PRESET_BALANCED = "balanced"
MODEL_PRESET_ECONOMY = "economy"
MODEL_PRESET_PRO = "pro"
MODEL_PRESETS = {MODEL_PRESET_AUTO, MODEL_PRESET_BALANCED, MODEL_PRESET_ECONOMY, MODEL_PRESET_PRO}
LEDGER_FILE = "quota_ledger.jsonl"


@dataclass(slots=True)
class ModelCallRecord:
    timestamp: datetime
    model_id: str
    role: str
    task_type: str
    unit: str
    amount: int = 1
    session_id: str | None = None
    reason: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
            "model_id": self.model_id,
            "role": self.role,
            "task_type": self.task_type,
            "unit": self.unit,
            "amount": self.amount,
            "session_id": self.session_id,
            "reason": self.reason,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "ModelCallRecord":
        timestamp_text = str(payload["timestamp"])
        timestamp = datetime.fromisoformat(timestamp_text)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return cls(
            timestamp=timestamp.astimezone(UTC),
            model_id=str(payload["model_id"]),
            role=str(payload.get("role", "")),
            task_type=str(payload.get("task_type", "")),
            unit=str(payload.get("unit", "request")),
            amount=int(payload.get("amount", 1)),
            session_id=str(payload["session_id"]) if payload.get("session_id") else None,
            reason=str(payload.get("reason", "")),
        )


class QuotaLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_workspace(cls, workspace_path: Path) -> "QuotaLedger":
        return cls(workspace_path / SESSION_DIR_NAME / LEDGER_FILE)

    def record(
        self,
        *,
        model_id: str,
        role: str,
        task_type: str,
        unit: str = "request",
        amount: int = 1,
        session_id: str | None = None,
        reason: str = "",
    ) -> ModelCallRecord:
        record = ModelCallRecord(
            timestamp=datetime.now(UTC),
            model_id=model_id,
            role=role,
            task_type=task_type,
            unit=unit,
            amount=amount,
            session_id=session_id,
            reason=reason,
        )
        self.path.parent.mkdir(exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_json(), ensure_ascii=False) + "\n")
        return record

    def load(self) -> list[ModelCallRecord]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records: list[ModelCallRecord] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    records.append(ModelCallRecord.from_json(payload))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return records

    def replace(self, records: list[ModelCallRecord]) -> None:
        self.path.parent.mkdir(exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record.to_json(), ensure_ascii=False) + "\n")
        tmp_path.replace(self.path)

    def clear(
        self,
        *,
        model_id: str | None = None,
        unit: str | None = None,
        role: str | None = None,
    ) -> int:
        records = self.load()
        kept: list[ModelCallRecord] = []
        removed = 0
        for record in records:
            if _record_matches(record, model_id=model_id, unit=unit, role=role):
                removed += 1
            else:
                kept.append(record)
        if removed:
            self.replace(kept)
        return removed


@dataclass(slots=True)
class QuotaWindowStatus:
    name: str
    limit: int
    used: int
    remaining: int
    resets_at: datetime | None

    @property
    def available(self) -> bool:
        return self.remaining > 0


@dataclass(slots=True)
class QuotaPolicyStatus:
    policy_id: str
    unit: str
    windows: list[QuotaWindowStatus] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return all(window.available for window in self.windows)

    @property
    def tightest_remaining(self) -> int | None:
        if not self.windows:
            return None
        return min(window.remaining for window in self.windows)

    @property
    def next_restore_at(self) -> datetime | None:
        restore_times = [window.resets_at for window in self.windows if not window.available and window.resets_at]
        if not restore_times:
            return None
        return min(restore_times)


@dataclass(slots=True)
class ModelQuotaStatus:
    model_id: str
    policy_id: str | None
    unit: str
    windows: list[QuotaWindowStatus] = field(default_factory=list)
    policy_statuses: list[QuotaPolicyStatus] = field(default_factory=list)

    @property
    def available(self) -> bool:
        if self.policy_statuses:
            return all(policy.available for policy in self.policy_statuses)
        return all(window.available for window in self.windows)

    @property
    def tightest_remaining(self) -> int | None:
        if self.policy_statuses:
            remaining = [
                policy.tightest_remaining
                for policy in self.policy_statuses
                if policy.tightest_remaining is not None
            ]
            return min(remaining) if remaining else None
        if not self.windows:
            return None
        return min(window.remaining for window in self.windows)

    @property
    def next_restore_at(self) -> datetime | None:
        if self.policy_statuses:
            restore_times = [
                policy.next_restore_at
                for policy in self.policy_statuses
                if policy.next_restore_at is not None
            ]
            return min(restore_times) if restore_times else None
        restore_times = [window.resets_at for window in self.windows if not window.available and window.resets_at]
        if not restore_times:
            return None
        return min(restore_times)

    @property
    def metered_units(self) -> list[str]:
        if not self.policy_statuses:
            return []
        return _dedupe([policy.unit for policy in self.policy_statuses])

    @property
    def metered(self) -> bool:
        return bool(self.policy_statuses)


class QuotaState:
    def __init__(self, policies: list[QuotaPolicyConfig], records: list[ModelCallRecord]) -> None:
        self.policies = policies
        self.records = records

    def status_for_model(self, model_id: str, now: datetime | None = None) -> ModelQuotaStatus:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        policies = self._policies_for_model(model_id)
        if not policies:
            return ModelQuotaStatus(model_id=model_id, policy_id=None, unit="request", windows=[])
        policy_statuses: list[QuotaPolicyStatus] = []
        for policy in policies:
            matching_records = [
                record
                for record in self.records
                if record.unit == policy.unit and self._model_matches_policy(record.model_id, policy)
            ]
            policy_statuses.append(
                QuotaPolicyStatus(
                    policy_id=policy.id,
                    unit=policy.unit,
                    windows=[
                        self._window_status(window, matching_records, now)
                        for window in policy.windows
                    ],
                )
            )
        windows = [window for policy_status in policy_statuses for window in policy_status.windows]
        units = _dedupe([policy.unit for policy in policies])
        return ModelQuotaStatus(
            model_id=model_id,
            policy_id=", ".join(policy.id for policy in policies),
            unit=units[0] if len(units) == 1 else ", ".join(units),
            windows=windows,
            policy_statuses=policy_statuses,
        )

    def _policy_for_model(self, model_id: str) -> QuotaPolicyConfig | None:
        policies = self._policies_for_model(model_id)
        return policies[0] if policies else None

    def _policies_for_model(self, model_id: str) -> list[QuotaPolicyConfig]:
        return [policy for policy in self.policies if self._model_matches_policy(model_id, policy)]

    def _model_matches_policy(self, model_id: str, policy: QuotaPolicyConfig) -> bool:
        return any(fnmatch.fnmatch(model_id, pattern) for pattern in policy.model_patterns)

    def _window_status(
        self,
        window,
        records: list[ModelCallRecord],
        now: datetime,
    ) -> QuotaWindowStatus:
        start, resets_at = _window_bounds(window, now)
        used_records = [record for record in records if record.timestamp >= start]
        used = sum(record.amount for record in used_records)
        remaining = max(window.limit - used, 0)
        if window.type == "rolling" and used >= window.limit and used_records:
            resets_at = min(
                record.timestamp + timedelta(seconds=window.duration_seconds or 0)
                for record in used_records
            )
        return QuotaWindowStatus(
            name=window.name,
            limit=window.limit,
            used=used,
            remaining=remaining,
            resets_at=resets_at if remaining == 0 else None,
        )


@dataclass(slots=True)
class ModelSelection:
    model_id: str
    role: str
    task_type: str
    reason: str
    routing_mode: str
    quota_status: ModelQuotaStatus | None = None


class QuotaAwareSelector:
    def __init__(
        self,
        config: HelmcodeConfig,
        ledger: QuotaLedger,
        routing_mode: str | None = None,
        model_preset: str | None = None,
    ) -> None:
        self.config = config
        self.ledger = ledger
        self.routing_mode = routing_mode or config.routing_mode
        self.model_preset = normalize_model_preset(model_preset)
        self.fixed_selector = ModelSelector(config.model_roles)
        self.profiles = {profile.id: profile for profile in config.model_profiles}

    def select(
        self,
        *,
        role: str,
        task_type: str | None = None,
        task: str = "",
        fallback_model_id: str | None = None,
        override_model_id: str | None = None,
        override_reason: str | None = None,
        prefer_different_from: str | None = None,
        reserved_records: list[ModelCallRecord] | None = None,
    ) -> ModelSelection:
        task_type = task_type or task_type_for_role(role, task)
        if override_model_id:
            status = self._status_for_model(override_model_id, reserved_records=reserved_records)
            return ModelSelection(
                model_id=override_model_id,
                role=role,
                task_type=task_type,
                reason=override_reason or "explicit --model override",
                routing_mode=self.routing_mode,
                quota_status=status,
            )
        if self.routing_mode == "fixed" or not self._has_routing_data():
            model_id = fallback_model_id or self.fixed_selector.select(role)
            status = self._status_for_model(model_id, reserved_records=reserved_records)
            return ModelSelection(
                model_id=model_id,
                role=role,
                task_type=task_type,
                reason=f"fixed role mapping for {role}",
                routing_mode="fixed",
                quota_status=status,
            )

        candidates = self._candidate_models(role, task_type, fallback_model_id)
        if prefer_different_from:
            different = [model_id for model_id in candidates if model_id != prefer_different_from]
            if different:
                candidates = different
        if not candidates:
            model_id = fallback_model_id or self.fixed_selector.select(role)
            return ModelSelection(
                model_id=model_id,
                role=role,
                task_type=task_type,
                reason=f"no profile matched {task_type}; used fixed role mapping",
                routing_mode="fixed",
            )

        quota_state = QuotaState(
            self.config.quota_policies,
            [*self.ledger.load(), *(reserved_records or [])],
        )
        exhausted: list[ModelQuotaStatus] = []
        for model_id in candidates:
            status = quota_state.status_for_model(model_id)
            if status.available:
                reason = f"selected for {task_type}"
                if self.model_preset not in {MODEL_PRESET_BALANCED, MODEL_PRESET_AUTO}:
                    reason += f" using {self.model_preset} preset"
                if status.policy_id:
                    reason += f"; quota policies {status.policy_id} have capacity"
                else:
                    reason += "; no quota policy limits this model"
                return ModelSelection(
                    model_id=model_id,
                    role=role,
                    task_type=task_type,
                    reason=reason,
                    routing_mode=self.routing_mode,
                    quota_status=status,
                )
            exhausted.append(status)

        restore_text = _restore_summary(exhausted)
        raise ModelError(f"No quota capacity for {role}/{task_type}. {restore_text}")

    def record_call(
        self,
        selection: ModelSelection,
        session_id: str | None = None,
        amount: int = 1,
        amounts_by_unit: dict[str, int] | None = None,
    ) -> None:
        units = selection.quota_status.metered_units if selection.quota_status else []
        if not units:
            units = ["request"]
        for unit in units:
            self.ledger.record(
                model_id=selection.model_id,
                role=selection.role,
                task_type=selection.task_type,
                unit=unit,
                amount=(amounts_by_unit or {}).get(unit, amount),
                session_id=session_id,
                reason=selection.reason,
            )

    def status_for_configured_models(self) -> list[ModelQuotaStatus]:
        model_ids = sorted({*self.config.model_roles.values(), *self.profiles.keys()})
        quota_state = QuotaState(self.config.quota_policies, self.ledger.load())
        return [quota_state.status_for_model(model_id) for model_id in model_ids if model_id]

    def _has_routing_data(self) -> bool:
        return bool(self.config.model_profiles or self.config.quota_policies)

    def _status_for_model(
        self,
        model_id: str,
        reserved_records: list[ModelCallRecord] | None = None,
    ) -> ModelQuotaStatus:
        return QuotaState(
            self.config.quota_policies,
            [*self.ledger.load(), *(reserved_records or [])],
        ).status_for_model(model_id)

    def _candidate_models(
        self,
        role: str,
        task_type: str,
        fallback_model_id: str | None,
    ) -> list[str]:
        preferred = [
            profile
            for profile in self.config.model_profiles
            if task_type in profile.preferred_for
        ]
        preferred = self._apply_model_preset(preferred)
        preferred.sort(key=self._profile_sort_key)
        candidates = [profile.id for profile in preferred]
        role_model = fallback_model_id or self.config.model_roles.get(role)
        if role_model:
            candidates.append(role_model)
        default_model = self.config.model_roles.get(MODEL_ROLE_DEFAULT)
        if default_model:
            candidates.append(default_model)
        return _expand_fallbacks(_dedupe(candidates), self.profiles)

    def _apply_model_preset(self, profiles: list[ModelProfileConfig]) -> list[ModelProfileConfig]:
        if self.model_preset != MODEL_PRESET_ECONOMY:
            return profiles
        cheaper_profiles = [profile for profile in profiles if profile.cost_tier != "high"]
        return cheaper_profiles or profiles

    def _profile_sort_key(self, profile: ModelProfileConfig) -> tuple[int, str]:
        cost = COST_ORDER.get(profile.cost_tier, COST_ORDER["medium"])
        if self.model_preset == MODEL_PRESET_PRO:
            cost = -cost
        return cost, profile.id


def classify_task(task: str) -> str:
    lowered = task.lower().strip()
    if any(token in lowered for token in ["review", "\u5ba1\u67e5", "\u8bc4\u5ba1", "\u68c0\u67e5 patch"]):
        return TASK_REVIEW
    if any(token in lowered for token in ["repair", "fix failing", "test failed", "\u4fee\u590d\u5931\u8d25"]):
        return TASK_REPAIR
    if _has_leading_plan_intent(lowered):
        return TASK_PLAN
    if any(
        token in lowered
        for token in [
            "implement",
            "add",
            "change",
            "refactor",
            "\u5f00\u53d1",
            "\u5b9e\u73b0",
            "\u4fee\u6539",
            "\u65b0\u589e",
        ]
    ):
        return TASK_CODE_PATCH
    if any(
        token in lowered
        for token in ["plan", "\u8ba1\u5212", "\u65b9\u6848", "architecture", "\u67b6\u6784", "\u5206\u6790"]
    ):
        return TASK_PLAN
    if any(token in lowered for token in ["summarize", "summary", "\u603b\u7ed3", "\u6982\u62ec"]):
        return TASK_SUMMARIZE
    if any(token in lowered for token in ["search", "find", "scan", "\u67e5\u627e", "\u626b\u63cf"]):
        return TASK_REPO_SCAN
    return TASK_CLASSIFY


def _has_leading_plan_intent(lowered: str) -> bool:
    if any(
        token in lowered
        for token in [
            " and implement",
            " then implement",
            " and add",
            " then add",
            "\u5e76\u5b9e\u73b0",
            "\u7136\u540e\u5b9e\u73b0",
            "\u5e76\u5f00\u53d1",
            "\u7136\u540e\u5f00\u53d1",
            "\u5e76\u4fee\u6539",
            "\u7136\u540e\u4fee\u6539",
        ]
    ):
        return False
    english_prefixes = (
        "plan",
        "explain",
        "analyze",
        "analyse",
        "describe",
        "design a plan",
        "write a plan",
    )
    if any(lowered == prefix or lowered.startswith(f"{prefix} ") for prefix in english_prefixes):
        return True
    return any(
        lowered.startswith(prefix)
        for prefix in [
            "\u8ba1\u5212",
            "\u5236\u5b9a\u8ba1\u5212",
            "\u5199\u4e00\u4e2a\u8ba1\u5212",
            "\u65b9\u6848",
            "\u8bbe\u8ba1\u65b9\u6848",
            "\u5206\u6790",
            "\u89e3\u91ca",
            "\u8bf4\u660e",
        ]
    )


def task_type_for_role(role: str, task: str = "") -> str:
    if role in ROLE_TASK_TYPES:
        return ROLE_TASK_TYPES[role]
    return classify_task(task)


def normalize_model_preset(value: object | None) -> str:
    if not isinstance(value, str) or not value:
        return MODEL_PRESET_BALANCED
    normalized = value.strip().lower()
    if normalized not in MODEL_PRESETS:
        raise ModelError(
            f"Unsupported model preset {value!r}; expected one of: "
            + ", ".join(sorted(MODEL_PRESETS))
        )
    return normalized


def _window_bounds(window, now: datetime) -> tuple[datetime, datetime]:
    if window.type == "rolling":
        duration = timedelta(seconds=window.duration_seconds or 0)
        return now - duration, now + duration
    if window.type == "calendar_day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if window.type == "calendar_week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=7)
    if window.type == "calendar_month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        return start, next_month
    raise ValueError(f"unsupported quota window type: {window.type}")


def _expand_fallbacks(candidates: list[str], profiles: dict[str, ModelProfileConfig]) -> list[str]:
    expanded: list[str] = []
    visiting: set[str] = set()

    def visit(model_id: str) -> None:
        if model_id in visiting:
            raise ModelError(f"Fallback cycle detected at model {model_id}")
        if model_id in expanded:
            return
        expanded.append(model_id)
        visiting.add(model_id)
        profile = profiles.get(model_id)
        if profile:
            for fallback in profile.fallback_models:
                visit(fallback)
        visiting.remove(model_id)

    for candidate in candidates:
        visit(candidate)
    return expanded


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _record_matches(
    record: ModelCallRecord,
    *,
    model_id: str | None,
    unit: str | None,
    role: str | None,
) -> bool:
    if model_id is not None and record.model_id != model_id:
        return False
    if unit is not None and record.unit != unit:
        return False
    if role is not None and record.role != role:
        return False
    return True


def _restore_summary(statuses: list[ModelQuotaStatus]) -> str:
    restore_times = [status.next_restore_at for status in statuses if status.next_restore_at]
    if not restore_times:
        return "No reset time is available."
    earliest = min(restore_times)
    return f"Earliest quota restores at {earliest.isoformat()}."
