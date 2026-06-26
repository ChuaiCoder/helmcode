from __future__ import annotations

from pathlib import Path

from helmcode.agent.allocation import CodingPlanTaskAllocator
from helmcode.core.config import (
    AgentProfileConfig,
    HelmcodeConfig,
    ModelProfileConfig,
    QuotaPolicyConfig,
    QuotaWindowConfig,
)
from helmcode.models.quota import QuotaAwareSelector, QuotaLedger


def _config() -> HelmcodeConfig:
    return HelmcodeConfig(
        model_roles={
            "default": "main:fast",
            "fast": "main:fast",
            "planning": "main:planner",
            "coding": "main:coder",
            "review": "main:review",
        },
        model_profiles=[
            ModelProfileConfig(
                id="main:fast",
                labels=["fast", "cheap"],
                preferred_for=["repo_scan", "summarize", "classify"],
                cost_tier="low",
            ),
            ModelProfileConfig(
                id="main:planner",
                labels=["reasoning"],
                preferred_for=["plan"],
                cost_tier="medium",
            ),
            ModelProfileConfig(
                id="main:coder",
                labels=["coding"],
                preferred_for=["code_patch", "repair"],
                cost_tier="high",
            ),
            ModelProfileConfig(
                id="main:review",
                labels=["review"],
                preferred_for=["review"],
                cost_tier="medium",
            ),
        ],
    )


def _allocator(config: HelmcodeConfig, tmp_path: Path) -> CodingPlanTaskAllocator:
    return CodingPlanTaskAllocator(
        config,
        QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl")),
    )


def test_complex_coding_task_uses_multi_agent_quota_saving_path(tmp_path: Path) -> None:
    allocation = _allocator(_config(), tmp_path).allocate(
        "refactor the architecture and implement a safer routing layer"
    )

    assert [assignment.agent_id for assignment in allocation.assignments] == [
        "scout",
        "planner",
        "coder",
        "reviewer",
    ]
    assert allocation.estimated_savings_score > 0
    assert allocation.strategy == "full multi-agent path with cheap context preparation"


def test_simple_coding_task_uses_direct_path(tmp_path: Path) -> None:
    allocation = _allocator(_config(), tmp_path).allocate("add a small helper")

    assert [assignment.agent_id for assignment in allocation.assignments] == ["planner", "coder"]
    assert allocation.complexity == "low"
    assert allocation.strategy == "quota-saving direct path"


def test_optional_reviewer_is_skipped_when_quota_is_exhausted(tmp_path: Path) -> None:
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="review_only",
            model_patterns=["main:review"],
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
        )
    ]
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="main:review", role="review", task_type="review")
    allocator = CodingPlanTaskAllocator(config, QuotaAwareSelector(config, ledger))

    allocation = allocator.allocate("refactor the architecture and implement routing")

    assert "reviewer" not in [assignment.agent_id for assignment in allocation.assignments]
    assert any(warning.startswith("skipped:reviewer:") for warning in allocation.warnings)
    assert allocation.blocked is False


def test_required_agent_quota_exhaustion_blocks_allocation(tmp_path: Path) -> None:
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="coder_only",
            model_patterns=["main:coder"],
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
        )
    ]
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="main:coder", role="coding", task_type="code_patch")
    allocator = CodingPlanTaskAllocator(config, QuotaAwareSelector(config, ledger))

    allocation = allocator.allocate("add a small helper")

    assert any(warning.startswith("blocked:coder:") for warning in allocation.warnings)
    assert allocation.blocked is True


def test_configured_agent_profile_replaces_builtin(tmp_path: Path) -> None:
    config = _config()
    config.agent_profiles = [
        AgentProfileConfig(
            id="planner",
            role="planning",
            task_type="plan",
            model_role="planning",
            purpose="custom planning policy",
            order=5,
            required=True,
        )
    ]

    allocation = _allocator(config, tmp_path).allocate("plan a refactor")

    planner = next(assignment for assignment in allocation.assignments if assignment.agent_id == "planner")
    assert planner.purpose == "custom planning policy"


def test_configured_agent_trigger_adds_real_assignment(tmp_path: Path) -> None:
    config = _config()
    config.agent_profiles = [
        AgentProfileConfig(
            id="security_reviewer",
            role="review",
            task_type="review",
            model_role="review",
            purpose="review security-sensitive code changes",
            order=45,
            required=False,
            triggers=["security"],
        )
    ]

    allocation = _allocator(config, tmp_path).allocate("add a security header helper")

    assert [assignment.agent_id for assignment in allocation.assignments] == [
        "scout",
        "planner",
        "coder",
        "security_reviewer",
    ]
    security_assignment = allocation.assignments[-1]
    assert security_assignment.model_id == "main:review"
    assert security_assignment.purpose == "review security-sensitive code changes"


def test_allocation_to_dict_exposes_runtime_contract(tmp_path: Path) -> None:
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="all_models",
            model_patterns=["main:*"],
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=10)],
        )
    ]

    allocation = _allocator(config, tmp_path).allocate("add a small helper")
    payload = allocation.to_dict()

    assert payload["task"] == "add a small helper"
    assert payload["blocked"] is False
    assert payload["estimated_savings_score"] == allocation.estimated_savings_score
    first_assignment = payload["assignments"][0]
    assert first_assignment["agent_id"] == "planner"
    assert first_assignment["quota_policy_id"] == "all_models"
    assert first_assignment["quota_remaining"] == 10
