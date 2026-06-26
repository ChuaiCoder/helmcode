from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from helmcode.agent.allocation import CodingPlanTaskAllocator
from helmcode.agent.runtime import AgentRuntime
from helmcode.agent.session import AgentSession
from helmcode.context.workspace import Workspace
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


def _allocator_with_preset(
    config: HelmcodeConfig,
    tmp_path: Path,
    preset: str,
) -> CodingPlanTaskAllocator:
    return CodingPlanTaskAllocator(
        config,
        QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl"), model_preset=preset),
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


def test_budget_cap_removes_optional_agents_before_blocking(tmp_path: Path) -> None:
    allocation = _allocator(_config(), tmp_path).allocate(
        "refactor the whole project architecture and implement a large routing change",
        max_cost_score=8,
    )

    assert [assignment.agent_id for assignment in allocation.assignments] == [
        "scout",
        "summarizer",
        "planner",
        "coder",
    ]
    assert allocation.selected_cost_score == 8
    assert allocation.budget_exceeded is False
    assert any(warning.startswith("skipped:reviewer:budget cap 8") for warning in allocation.warnings)


def test_budget_cap_blocks_when_required_path_still_exceeds_budget(tmp_path: Path) -> None:
    allocation = _allocator(_config(), tmp_path).allocate("add a small helper", max_cost_score=3)

    assert [assignment.agent_id for assignment in allocation.assignments] == ["planner", "coder"]
    assert allocation.selected_cost_score == 6
    assert allocation.budget_exceeded is True


def test_simple_coding_task_uses_direct_path(tmp_path: Path) -> None:
    allocation = _allocator(_config(), tmp_path).allocate("add a small helper")

    assert [assignment.agent_id for assignment in allocation.assignments] == ["planner", "coder"]
    assert allocation.complexity == "low"
    assert allocation.strategy == "quota-saving direct path"


def test_quota_allocation_uses_cheaper_profiled_coding_model(tmp_path: Path) -> None:
    config = _config()
    config.model_profiles.append(
        ModelProfileConfig(
            id="main:cheap-coder",
            labels=["coding", "cheap"],
            preferred_for=["code_patch"],
            cost_tier="low",
        )
    )

    allocation = _allocator(config, tmp_path).allocate("add a small helper")

    assert [assignment.model_id for assignment in allocation.assignments] == [
        "main:planner",
        "main:cheap-coder",
    ]
    assert allocation.selected_cost_score == 3
    assert allocation.estimated_savings_score == 5


def test_pro_preset_allocation_prefers_high_capability_profile(tmp_path: Path) -> None:
    config = _config()
    config.model_profiles.append(
        ModelProfileConfig(
            id="main:cheap-coder",
            labels=["coding", "cheap"],
            preferred_for=["code_patch"],
            cost_tier="low",
        )
    )

    allocation = _allocator_with_preset(config, tmp_path, "pro").allocate("add a small helper")

    assert allocation.model_preset == "pro"
    assert [assignment.model_id for assignment in allocation.assignments] == [
        "main:planner",
        "main:coder",
    ]
    coder = next(assignment for assignment in allocation.assignments if assignment.agent_id == "coder")
    assert "using pro preset" in coder.reason


def test_auto_preset_low_complexity_uses_balanced_route(tmp_path: Path) -> None:
    config = _config()
    config.model_profiles.append(
        ModelProfileConfig(
            id="main:cheap-coder",
            labels=["coding", "cheap"],
            preferred_for=["code_patch"],
            cost_tier="low",
        )
    )

    allocation = _allocator_with_preset(config, tmp_path, "auto").allocate("add a small helper")

    assert allocation.model_preset == "auto"
    assert allocation.effective_model_preset == "balanced"
    assert [assignment.model_id for assignment in allocation.assignments] == [
        "main:planner",
        "main:cheap-coder",
    ]


def test_auto_preset_complex_task_uses_pro_route(tmp_path: Path) -> None:
    config = _config()
    config.model_profiles.append(
        ModelProfileConfig(
            id="main:cheap-coder",
            labels=["coding", "cheap"],
            preferred_for=["code_patch"],
            cost_tier="low",
        )
    )

    allocation = _allocator_with_preset(config, tmp_path, "auto").allocate(
        "refactor the whole project architecture and implement a large routing change"
    )

    assert allocation.model_preset == "auto"
    assert allocation.effective_model_preset == "pro"
    coder = next(assignment for assignment in allocation.assignments if assignment.agent_id == "coder")
    assert coder.model_id == "main:coder"
    assert "using pro preset" in coder.reason


def test_runtime_auto_preset_reuses_allocation_effective_preset(tmp_path: Path) -> None:
    config = _config()
    config.model_profiles.append(
        ModelProfileConfig(
            id="main:cheap-coder",
            labels=["coding", "cheap"],
            preferred_for=["code_patch"],
            cost_tier="low",
        )
    )
    selector = QuotaAwareSelector(
        config,
        QuotaLedger(tmp_path / "quota.jsonl"),
        model_preset="auto",
    )
    runtime = AgentRuntime(
        workspace=Workspace.discover(tmp_path),
        selector=selector,
    )
    task = "refactor the whole project architecture and implement a large routing change"
    session = AgentSession(
        session_id="test-session",
        workspace_path=tmp_path,
        user_task=task,
        created_at=datetime.now(UTC),
    )

    allocation = runtime.allocate_task(session=session, task=task)
    selection = runtime.select_model(
        session=session,
        role="coding",
        task_type="code_patch",
        task=task,
        fallback_model_id="main:coder",
        agent_id="coder",
    )

    assert allocation is not None
    assert allocation.effective_model_preset == "pro"
    assert selection.model_id == "main:coder"
    assert "using pro preset" in selection.reason
    assert selector.model_preset == "auto"


def test_scoped_model_override_changes_only_matching_agent(tmp_path: Path) -> None:
    allocation = _allocator(_config(), tmp_path).allocate(
        "add a small helper",
        model_overrides={"coder": "main:pro-coder"},
    )

    assert [assignment.model_id for assignment in allocation.assignments] == [
        "main:planner",
        "main:pro-coder",
    ]
    coder = next(assignment for assignment in allocation.assignments if assignment.agent_id == "coder")
    assert coder.reason == "explicit model override for coder"
    assert allocation.selected_cost_score == 4
    assert allocation.estimated_savings_score == 4


def test_fixed_allocation_keeps_configured_coding_role_when_cheaper_profile_exists(
    tmp_path: Path,
) -> None:
    config = _config()
    config.routing_mode = "fixed"
    config.model_profiles.append(
        ModelProfileConfig(
            id="main:cheap-coder",
            labels=["coding", "cheap"],
            preferred_for=["code_patch"],
            cost_tier="low",
        )
    )

    allocation = _allocator(config, tmp_path).allocate("add a small helper")

    assert [assignment.model_id for assignment in allocation.assignments] == [
        "main:planner",
        "main:coder",
    ]
    assert allocation.selected_cost_score == 6
    assert allocation.estimated_savings_score == 2


def test_plan_task_strategy_matches_plan_only_agents(tmp_path: Path) -> None:
    allocation = _allocator(_config(), tmp_path).allocate("plan repository architecture")

    assert [assignment.agent_id for assignment in allocation.assignments] == ["scout", "planner"]
    assert allocation.strategy == "scout-planning path with cheap repository discovery"


def test_repair_task_strategy_matches_repair_agents(tmp_path: Path) -> None:
    allocation = _allocator(_config(), tmp_path).allocate("fix failing tests around architecture")

    assert [assignment.agent_id for assignment in allocation.assignments] == ["scout", "fixer", "reviewer"]
    assert allocation.strategy == "scout-repair-review path"


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


def test_allocation_reserves_optional_agent_quota_without_recording_usage(tmp_path: Path) -> None:
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="fast_only",
            model_patterns=["main:fast"],
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
        )
    ]
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    allocator = CodingPlanTaskAllocator(config, QuotaAwareSelector(config, ledger))

    allocation = allocator.allocate("refactor the whole project architecture and implement a large routing change")

    assert [assignment.agent_id for assignment in allocation.assignments] == [
        "scout",
        "planner",
        "coder",
        "reviewer",
    ]
    assert any(warning.startswith("skipped:summarizer:") for warning in allocation.warnings)
    assert ledger.load() == []


def test_allocation_reserves_required_agent_quota_and_blocks_overbooking(tmp_path: Path) -> None:
    config = _config()
    shared_model = "main:shared"
    config.model_roles["default"] = shared_model
    config.model_roles["planning"] = shared_model
    config.model_roles["coding"] = shared_model
    config.model_profiles = [
        ModelProfileConfig(
            id=shared_model,
            preferred_for=["plan", "code_patch"],
            cost_tier="high",
        )
    ]
    config.quota_policies = [
        QuotaPolicyConfig(
            id="shared_once",
            model_patterns=[shared_model],
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
        )
    ]
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    allocator = CodingPlanTaskAllocator(config, QuotaAwareSelector(config, ledger))

    allocation = allocator.allocate("add a small helper")

    assert [assignment.agent_id for assignment in allocation.assignments] == ["planner"]
    assert any(warning.startswith("blocked:coder:") for warning in allocation.warnings)
    assert allocation.blocked is True
    assert ledger.load() == []


def test_optional_reservation_is_released_for_required_agent_quota(tmp_path: Path) -> None:
    config = _config()
    shared_model = "main:shared"
    config.model_roles["default"] = shared_model
    config.model_roles["fast"] = shared_model
    config.model_roles["planning"] = shared_model
    config.model_profiles = [
        ModelProfileConfig(
            id=shared_model,
            preferred_for=["repo_scan", "plan"],
            cost_tier="medium",
        )
    ]
    config.quota_policies = [
        QuotaPolicyConfig(
            id="shared_once",
            model_patterns=[shared_model],
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
        )
    ]
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    allocator = CodingPlanTaskAllocator(config, QuotaAwareSelector(config, ledger))

    allocation = allocator.allocate("plan the architecture change")

    assert [assignment.agent_id for assignment in allocation.assignments] == ["planner"]
    assert any(
        warning.startswith("skipped:scout:released optional reservation for required planner")
        for warning in allocation.warnings
    )
    assert allocation.blocked is False
    assert ledger.load() == []


def test_token_quota_reserves_estimated_agent_tokens(tmp_path: Path) -> None:
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="planning_tokens",
            model_patterns=["main:planner"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=3_000)],
        )
    ]
    allocation = _allocator(config, tmp_path).allocate("plan repository architecture")

    planner = next(assignment for assignment in allocation.assignments if assignment.agent_id == "planner")
    assert planner.quota_unit == "token"
    assert planner.quota_reserved_amount == 2_500
    assert planner.quota_remaining == 3_000
    assert planner.quota_remaining_after == 500


def test_explicit_context_reference_increases_token_reservation(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("a" * 400, encoding="utf-8")
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="planning_tokens",
            model_patterns=["main:planner"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=3_000)],
        )
    ]
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    allocator = CodingPlanTaskAllocator(
        config,
        QuotaAwareSelector(config, ledger),
        workspace=Workspace.discover(tmp_path),
    )

    allocation = allocator.allocate("plan repository architecture using @README.md")

    planner = next(assignment for assignment in allocation.assignments if assignment.agent_id == "planner")
    assert planner.context_token_estimate == 100
    assert planner.quota_reserved_amount == 2_600
    assert planner.quota_remaining_after == 400
    assert planner.quota_reservations[0]["context_token_estimate"] == 100


def test_explicit_directory_reference_increases_token_reservation(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "a.py").write_text("a" * 200, encoding="utf-8")
    (source_dir / "b.py").write_text("b" * 200, encoding="utf-8")
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="planning_tokens",
            model_patterns=["main:planner"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=3_000)],
        )
    ]
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    allocator = CodingPlanTaskAllocator(
        config,
        QuotaAwareSelector(config, ledger),
        workspace=Workspace.discover(tmp_path),
    )

    allocation = allocator.allocate("plan repository architecture using @src")

    planner = next(assignment for assignment in allocation.assignments if assignment.agent_id == "planner")
    assert planner.context_token_estimate == 100
    assert planner.quota_reserved_amount == 2_600


def test_allocation_reserves_request_and_token_quota_for_same_agent(tmp_path: Path) -> None:
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="planning_requests",
            model_patterns=["main:planner"],
            unit="request",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=2)],
        ),
        QuotaPolicyConfig(
            id="planning_tokens",
            model_patterns=["main:planner"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=3_000)],
        ),
    ]
    allocation = _allocator(config, tmp_path).allocate("plan repository architecture")

    planner = next(assignment for assignment in allocation.assignments if assignment.agent_id == "planner")
    assert planner.quota_policy_id == "planning_requests"
    assert planner.quota_reservations == [
        {
            "policy_id": "planning_requests",
            "unit": "request",
            "reserved_amount": 1,
            "remaining": 2,
            "remaining_after": 1,
            "context_token_estimate": 0,
            "resets_at": None,
        },
        {
            "policy_id": "planning_tokens",
            "unit": "token",
            "reserved_amount": 2_500,
            "remaining": 3_000,
            "remaining_after": 500,
            "context_token_estimate": 0,
            "resets_at": None,
        },
    ]


def test_allocation_blocks_when_second_matching_policy_lacks_capacity(tmp_path: Path) -> None:
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="planning_requests",
            model_patterns=["main:planner"],
            unit="request",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=2)],
        ),
        QuotaPolicyConfig(
            id="planning_tokens",
            model_patterns=["main:planner"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=2_000)],
        ),
    ]
    allocation = _allocator(config, tmp_path).allocate("plan repository architecture")

    assert [assignment.agent_id for assignment in allocation.assignments] == ["scout"]
    assert any(
        "blocked:planner:main:planner has insufficient quota capacity under planning_tokens" in warning
        for warning in allocation.warnings
    )
    assert allocation.blocked is True


def test_token_quota_blocks_when_estimated_agent_tokens_exceed_remaining(tmp_path: Path) -> None:
    config = _config()
    config.quota_policies = [
        QuotaPolicyConfig(
            id="planning_tokens",
            model_patterns=["main:planner"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=2_000)],
        )
    ]
    allocation = _allocator(config, tmp_path).allocate("plan repository architecture")

    assert [assignment.agent_id for assignment in allocation.assignments] == ["scout"]
    assert any(
        "blocked:planner:main:planner has insufficient quota capacity under planning_tokens" in warning
        for warning in allocation.warnings
    )
    assert allocation.blocked is True


def test_configured_agent_estimated_tokens_control_token_reservation(tmp_path: Path) -> None:
    config = _config()
    config.agent_profiles = [
        AgentProfileConfig(
            id="planner",
            role="planning",
            task_type="plan",
            model_role="planning",
            purpose="custom smaller planning budget",
            order=30,
            required=True,
            estimated_tokens=1_000,
        )
    ]
    config.quota_policies = [
        QuotaPolicyConfig(
            id="planning_tokens",
            model_patterns=["main:planner"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1_200)],
        )
    ]

    allocation = _allocator(config, tmp_path).allocate("plan repository architecture")

    planner = next(assignment for assignment in allocation.assignments if assignment.agent_id == "planner")
    assert planner.quota_reserved_amount == 1_000
    assert planner.quota_remaining_after == 200


def test_fixed_routing_allocation_still_blocks_required_exhausted_quota(tmp_path: Path) -> None:
    config = _config()
    config.routing_mode = "fixed"
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

    assert any("main:coder has no quota capacity under coder_only" in warning for warning in allocation.warnings)
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

    allocation = _allocator(config, tmp_path).allocate("add a small helper", max_cost_score=3)
    payload = allocation.to_dict()

    assert payload["task"] == "add a small helper"
    assert payload["model_preset"] == "balanced"
    assert payload["effective_model_preset"] == "balanced"
    assert payload["blocked"] is False
    assert payload["max_cost_score"] == 3
    assert payload["budget_exceeded"] is True
    assert payload["baseline_calls"] == 2
    assert payload["baseline_model_id"] == "main:coder"
    assert payload["estimated_savings_score"] == allocation.estimated_savings_score
    first_assignment = payload["assignments"][0]
    assert first_assignment["agent_id"] == "planner"
    assert first_assignment["model_cost_tier"] == "medium"
    assert first_assignment["quota_policy_id"] == "all_models"
    assert first_assignment["quota_remaining"] == 10
    assert first_assignment["quota_remaining_after"] == 9
    assert payload["cost_breakdown"] == {
        "baseline": {"model_id": "main:coder", "calls": 2, "cost_score": 8},
        "selected": {
            "calls": 2,
            "cost_score": 6,
            "required_cost_score": 6,
            "optional_cost_score": 0,
            "by_tier": {"medium": 2, "high": 4},
        },
        "estimated_savings_score": 2,
    }
