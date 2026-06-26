from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from helmcode.core.config import (
    HelmcodeConfig,
    ModelProfileConfig,
    ProviderConfig,
    QuotaPolicyConfig,
    QuotaWindowConfig,
)
from helmcode.core.exceptions import ModelError
from helmcode.models.quota import (
    TASK_CODE_PATCH,
    TASK_PLAN,
    TASK_REVIEW,
    ModelCallRecord,
    QuotaAwareSelector,
    QuotaLedger,
    QuotaState,
    classify_task,
    normalize_model_preset,
)


def _config(
    *,
    roles: dict[str, str] | None = None,
    profiles: list[ModelProfileConfig] | None = None,
    policies: list[QuotaPolicyConfig] | None = None,
) -> HelmcodeConfig:
    return HelmcodeConfig(
        providers=[
            ProviderConfig(
                id="main",
                type="openai_compatible",
                base_url="https://example.com/v1",
                api_key_env="API_KEY",
            )
        ],
        model_roles=roles or {"default": "main:fast", "coding": "main:strong", "review": "main:review"},
        model_profiles=profiles or [],
        quota_policies=policies or [],
    )


def test_old_config_without_profiles_keeps_fixed_selection(tmp_path: Path) -> None:
    config = _config(roles={"default": "main:fast", "coding": "main:strong"})
    selector = QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl"))

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )

    assert selection.model_id == "main:strong"
    assert selection.routing_mode == "fixed"


def test_quota_selection_prefers_lower_cost_profile_over_role_mapping(tmp_path: Path) -> None:
    config = _config(
        roles={"default": "main:fast", "coding": "main:strong"},
        profiles=[
            ModelProfileConfig(id="main:strong", preferred_for=[TASK_CODE_PATCH], cost_tier="high"),
            ModelProfileConfig(id="main:cheap-code", preferred_for=[TASK_CODE_PATCH], cost_tier="low"),
        ],
    )
    selector = QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl"), routing_mode="quota")

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )

    assert selection.model_id == "main:cheap-code"
    assert selection.routing_mode == "quota"


def test_fixed_selection_keeps_role_mapping_with_cheaper_profile(tmp_path: Path) -> None:
    config = _config(
        roles={"default": "main:fast", "coding": "main:strong"},
        profiles=[
            ModelProfileConfig(id="main:strong", preferred_for=[TASK_CODE_PATCH], cost_tier="high"),
            ModelProfileConfig(id="main:cheap-code", preferred_for=[TASK_CODE_PATCH], cost_tier="low"),
        ],
    )
    selector = QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl"), routing_mode="fixed")

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )

    assert selection.model_id == "main:strong"
    assert selection.routing_mode == "fixed"


def test_pro_preset_prefers_higher_cost_profile(tmp_path: Path) -> None:
    config = _config(
        roles={"default": "main:fast", "coding": "main:strong"},
        profiles=[
            ModelProfileConfig(id="main:strong", preferred_for=[TASK_CODE_PATCH], cost_tier="high"),
            ModelProfileConfig(id="main:cheap-code", preferred_for=[TASK_CODE_PATCH], cost_tier="low"),
        ],
    )
    selector = QuotaAwareSelector(
        config,
        QuotaLedger(tmp_path / "quota.jsonl"),
        routing_mode="quota",
        model_preset="pro",
    )

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )

    assert selection.model_id == "main:strong"
    assert "using pro preset" in selection.reason


def test_economy_preset_avoids_high_cost_profile_when_cheaper_exists(tmp_path: Path) -> None:
    config = _config(
        roles={"default": "main:fast", "coding": "main:strong"},
        profiles=[
            ModelProfileConfig(id="main:strong", preferred_for=[TASK_CODE_PATCH], cost_tier="high"),
            ModelProfileConfig(id="main:mid-code", preferred_for=[TASK_CODE_PATCH], cost_tier="medium"),
            ModelProfileConfig(id="main:cheap-code", preferred_for=[TASK_CODE_PATCH], cost_tier="low"),
        ],
    )
    selector = QuotaAwareSelector(
        config,
        QuotaLedger(tmp_path / "quota.jsonl"),
        routing_mode="quota",
        model_preset="economy",
    )

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )

    assert selection.model_id == "main:cheap-code"
    assert "using economy preset" in selection.reason


def test_normalize_model_preset_accepts_auto() -> None:
    assert normalize_model_preset("auto") == "auto"


def test_direct_auto_selector_behaves_like_balanced_without_complexity_context(tmp_path: Path) -> None:
    config = _config(
        roles={"default": "main:fast", "coding": "main:strong"},
        profiles=[
            ModelProfileConfig(id="main:strong", preferred_for=[TASK_CODE_PATCH], cost_tier="high"),
            ModelProfileConfig(id="main:cheap-code", preferred_for=[TASK_CODE_PATCH], cost_tier="low"),
        ],
    )
    selector = QuotaAwareSelector(
        config,
        QuotaLedger(tmp_path / "quota.jsonl"),
        routing_mode="quota",
        model_preset="auto",
    )

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )

    assert selection.model_id == "main:cheap-code"
    assert "using auto preset" not in selection.reason


def test_quota_selection_uses_next_lowest_cost_profile_when_cheapest_is_exhausted(
    tmp_path: Path,
) -> None:
    policy = QuotaPolicyConfig(
        id="cheap_only",
        model_patterns=["main:cheap-code"],
        windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
    )
    config = _config(
        roles={"default": "main:fast", "coding": "main:strong"},
        profiles=[
            ModelProfileConfig(id="main:strong", preferred_for=[TASK_CODE_PATCH], cost_tier="high"),
            ModelProfileConfig(id="main:cheap-code", preferred_for=[TASK_CODE_PATCH], cost_tier="low"),
            ModelProfileConfig(id="main:mid-code", preferred_for=[TASK_CODE_PATCH], cost_tier="medium"),
        ],
        policies=[policy],
    )
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="main:cheap-code", role="coding", task_type=TASK_CODE_PATCH)
    selector = QuotaAwareSelector(config, ledger, routing_mode="quota")

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )

    assert selection.model_id == "main:mid-code"


def test_fixed_selection_records_configured_quota_unit(tmp_path: Path) -> None:
    policy = QuotaPolicyConfig(
        id="prompt_calls",
        model_patterns=["main:*"],
        unit="prompt_call",
        windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=10)],
    )
    config = _config(policies=[policy])
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    selector = QuotaAwareSelector(config, ledger, routing_mode="fixed")

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )
    selector.record_call(selection, session_id="session")

    records = ledger.load()
    assert records[0].unit == "prompt_call"


def test_quota_state_combines_multiple_matching_policies() -> None:
    now = datetime.now(UTC)
    policies = [
        QuotaPolicyConfig(
            id="requests",
            model_patterns=["main:strong"],
            unit="request",
            windows=[QuotaWindowConfig(name="daily", type="calendar_day", limit=2)],
        ),
        QuotaPolicyConfig(
            id="tokens",
            model_patterns=["main:strong"],
            unit="token",
            windows=[QuotaWindowConfig(name="daily", type="calendar_day", limit=100)],
        ),
    ]
    records = [
        ModelCallRecord(now, "main:strong", "coding", TASK_CODE_PATCH, "request", amount=1),
        ModelCallRecord(now, "main:strong", "coding", TASK_CODE_PATCH, "token", amount=60),
    ]

    status = QuotaState(policies, records).status_for_model("main:strong", now=now)

    assert status.policy_id == "requests, tokens"
    assert status.unit == "request, token"
    assert status.metered_units == ["request", "token"]
    assert status.available is True
    assert [(policy.policy_id, policy.unit, policy.tightest_remaining) for policy in status.policy_statuses] == [
        ("requests", "request", 1),
        ("tokens", "token", 40),
    ]


def test_selector_blocks_when_any_matching_policy_is_exhausted(tmp_path: Path) -> None:
    policies = [
        QuotaPolicyConfig(
            id="requests",
            model_patterns=["main:strong"],
            unit="request",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=10)],
        ),
        QuotaPolicyConfig(
            id="tokens",
            model_patterns=["main:strong"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=50)],
        ),
    ]
    config = _config(
        roles={"default": "main:strong", "coding": "main:strong"},
        policies=policies,
    )
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="main:strong", role="coding", task_type=TASK_CODE_PATCH, unit="token", amount=50)
    selector = QuotaAwareSelector(config, ledger)

    try:
        selector.select(
            role="coding",
            task_type=TASK_CODE_PATCH,
            task="implement feature",
            fallback_model_id="main:strong",
        )
    except ModelError as exc:
        assert "No quota capacity" in str(exc)
    else:
        raise AssertionError("token exhaustion should block even when request quota remains")


def test_record_call_records_every_metered_unit(tmp_path: Path) -> None:
    policies = [
        QuotaPolicyConfig(
            id="requests",
            model_patterns=["main:strong"],
            unit="request",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=10)],
        ),
        QuotaPolicyConfig(
            id="tokens",
            model_patterns=["main:strong"],
            unit="token",
            windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=100)],
        ),
    ]
    config = _config(policies=policies)
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    selector = QuotaAwareSelector(config, ledger, routing_mode="fixed")

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )
    selector.record_call(selection, session_id="session", amounts_by_unit={"request": 1, "token": 42})

    assert [(record.unit, record.amount) for record in ledger.load()] == [("request", 1), ("token", 42)]


def test_rolling_window_ignores_expired_records() -> None:
    now = datetime.now(UTC)
    policy = QuotaPolicyConfig(
        id="main_plan",
        model_patterns=["main:*"],
        unit="request",
        windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=100, limit=2)],
    )
    records = [
        ModelCallRecord(now - timedelta(seconds=200), "main:strong", "coding", TASK_CODE_PATCH, "request"),
        ModelCallRecord(now - timedelta(seconds=10), "main:strong", "coding", TASK_CODE_PATCH, "request"),
    ]

    status = QuotaState([policy], records).status_for_model("main:strong", now=now)

    assert status.windows[0].used == 1
    assert status.windows[0].remaining == 1
    assert status.available is True


def test_selector_uses_fallback_when_preferred_model_is_exhausted(tmp_path: Path) -> None:
    policy = QuotaPolicyConfig(
        id="strong_only",
        model_patterns=["main:strong"],
        windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
    )
    config = _config(
        profiles=[
            ModelProfileConfig(
                id="main:strong",
                preferred_for=[TASK_CODE_PATCH],
                cost_tier="high",
                fallback_models=["main:fast"],
            ),
            ModelProfileConfig(id="main:fast", preferred_for=[TASK_CODE_PATCH], cost_tier="low"),
        ],
        policies=[policy],
    )
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="main:strong", role="coding", task_type=TASK_CODE_PATCH)
    selector = QuotaAwareSelector(config, ledger)

    selection = selector.select(
        role="coding",
        task_type=TASK_CODE_PATCH,
        task="implement feature",
        fallback_model_id="main:strong",
    )

    assert selection.model_id == "main:fast"


def test_selector_reports_restore_time_when_shared_policy_is_exhausted(tmp_path: Path) -> None:
    policy = QuotaPolicyConfig(
        id="shared",
        model_patterns=["main:*"],
        windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
    )
    config = _config(
        profiles=[
            ModelProfileConfig(id="main:strong", preferred_for=[TASK_CODE_PATCH], fallback_models=["main:fast"]),
            ModelProfileConfig(id="main:fast", preferred_for=[TASK_CODE_PATCH], cost_tier="low"),
        ],
        policies=[policy],
    )
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="main:strong", role="coding", task_type=TASK_CODE_PATCH)
    selector = QuotaAwareSelector(config, ledger)

    try:
        selector.select(
            role="coding",
            task_type=TASK_CODE_PATCH,
            task="implement feature",
            fallback_model_id="main:strong",
        )
    except ModelError as exc:
        assert "Earliest quota restores" in str(exc)
    else:
        raise AssertionError("shared exhausted policy should block all matching models")


def test_review_selection_prefers_model_different_from_coding(tmp_path: Path) -> None:
    config = _config(
        roles={"default": "main:fast", "review": "main:strong"},
        profiles=[
            ModelProfileConfig(id="main:strong", preferred_for=[TASK_REVIEW], cost_tier="high"),
            ModelProfileConfig(id="main:review", preferred_for=[TASK_REVIEW], cost_tier="low"),
        ],
    )
    selector = QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl"))

    selection = selector.select(
        role="review",
        task_type=TASK_REVIEW,
        task="review patch",
        fallback_model_id="main:strong",
        prefer_different_from="main:strong",
    )

    assert selection.model_id == "main:review"


def test_classify_leading_plan_intent_before_change_tokens() -> None:
    assert classify_task("plan the architecture change") == TASK_PLAN


def test_classify_plan_and_implement_as_coding_task() -> None:
    assert classify_task("plan and implement the architecture change") == TASK_CODE_PATCH


def test_classify_refactor_architecture_as_coding_task() -> None:
    assert classify_task("refactor the architecture and implement safer routing") == TASK_CODE_PATCH
