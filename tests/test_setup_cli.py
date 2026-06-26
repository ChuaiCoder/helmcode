from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.cli.commands.setup import build_setup_config
from helmcode.core.config import HelmcodeConfig, default_config_path, load_config, load_yaml


def test_build_setup_config_creates_profiles_and_quota_policies() -> None:
    config = build_setup_config(
        provider_id="main",
        base_url="https://example.com/v1",
        api_key_env="MAIN_API_KEY",
        model="general",
        fast_model="fast",
        planning_model="planner",
        coding_model="coder",
        review_model="reviewer",
        permission_mode="suggest",
        routing_mode="quota",
        fast_daily_limit=100,
        planning_daily_limit=50,
        coding_daily_limit=10,
        review_daily_limit=20,
    )

    assert config.model_roles["default"] == "main:general"
    assert config.model_roles["fast"] == "main:fast"
    assert config.model_roles["planning"] == "main:planner"
    assert config.model_roles["coding"] == "main:coder"
    assert config.model_roles["review"] == "main:reviewer"
    profiles = {profile.id: profile for profile in config.model_profiles}
    assert profiles["main:fast"].cost_tier == "low"
    assert "repo_scan" in profiles["main:fast"].preferred_for
    assert profiles["main:coder"].cost_tier == "high"
    assert "code_patch" in profiles["main:coder"].preferred_for
    assert [policy.id for policy in config.quota_policies] == [
        "fast_daily",
        "planning_daily",
        "coding_daily",
        "review_daily",
    ]
    assert config.quota_policies[2].windows[0].limit == 10


def test_build_setup_config_creates_token_quota_policies() -> None:
    config = build_setup_config(
        provider_id="main",
        base_url="https://example.com/v1",
        api_key_env="MAIN_API_KEY",
        model="general",
        fast_model="fast",
        planning_model="planner",
        coding_model="coder",
        review_model="reviewer",
        permission_mode="suggest",
        routing_mode="quota",
        fast_daily_token_limit=20_000,
        planning_daily_token_limit=30_000,
        coding_daily_token_limit=80_000,
        review_daily_token_limit=40_000,
    )

    assert [policy.id for policy in config.quota_policies] == [
        "fast_daily_tokens",
        "planning_daily_tokens",
        "coding_daily_tokens",
        "review_daily_tokens",
    ]
    assert [policy.unit for policy in config.quota_policies] == ["token", "token", "token", "token"]
    assert config.quota_policies[2].model_patterns == ["main:coder"]
    assert config.quota_policies[2].windows[0].limit == 80_000


def test_build_setup_config_rejects_role_request_and_token_limits() -> None:
    try:
        build_setup_config(
            provider_id="main",
            base_url="https://example.com/v1",
            api_key_env="MAIN_API_KEY",
            model="general",
            fast_model="fast",
            planning_model="planner",
            coding_model="coder",
            review_model="reviewer",
            permission_mode="suggest",
            routing_mode="quota",
            coding_daily_limit=10,
            coding_daily_token_limit=80_000,
        )
    except ValueError as exc:
        assert "--coding-daily-limit" in str(exc)
        assert "--coding-daily-token-limit" in str(exc)
    else:
        raise AssertionError("setup should reject mixed quota units for one role")


def test_build_setup_config_rejects_mixed_units_for_shared_model() -> None:
    try:
        build_setup_config(
            provider_id="main",
            base_url="https://example.com/v1",
            api_key_env="MAIN_API_KEY",
            model="general",
            fast_model="shared",
            planning_model="shared",
            coding_model="coder",
            review_model="reviewer",
            permission_mode="suggest",
            routing_mode="quota",
            fast_daily_limit=100,
            planning_daily_token_limit=30_000,
        )
    except ValueError as exc:
        assert "cannot mix request and token limits" in str(exc)
        assert "main:shared" in str(exc)
    else:
        raise AssertionError("setup should reject mixed quota units for one model")


def test_build_setup_config_merges_same_limit_for_shared_model() -> None:
    config = build_setup_config(
        provider_id="main",
        base_url="https://example.com/v1",
        api_key_env="MAIN_API_KEY",
        model="general",
        fast_model="shared",
        planning_model="shared",
        coding_model="coder",
        review_model="reviewer",
        permission_mode="suggest",
        routing_mode="quota",
        fast_daily_token_limit=30_000,
        planning_daily_token_limit=30_000,
    )

    assert len(config.quota_policies) == 1
    assert config.quota_policies[0].id == "fast_planning_daily_tokens"
    assert config.quota_policies[0].model_patterns == ["main:shared"]
    assert config.quota_policies[0].unit == "token"
    assert config.quota_policies[0].windows[0].limit == 30_000


def test_build_setup_config_rejects_different_limits_for_shared_model() -> None:
    try:
        build_setup_config(
            provider_id="main",
            base_url="https://example.com/v1",
            api_key_env="MAIN_API_KEY",
            model="general",
            fast_model="shared",
            planning_model="shared",
            coding_model="coder",
            review_model="reviewer",
            permission_mode="suggest",
            routing_mode="quota",
            fast_daily_limit=100,
            planning_daily_limit=50,
        )
    except ValueError as exc:
        assert "policies are model-level" in str(exc)
        assert "different request daily limits" in str(exc)
    else:
        raise AssertionError("setup should reject conflicting limits for one model")


def test_default_config_includes_codingplan_cost_tiers() -> None:
    config = HelmcodeConfig.model_validate(load_yaml(default_config_path()))
    profiles = {profile.id: profile for profile in config.model_profiles}

    assert profiles[config.model_roles["fast"]].cost_tier == "low"
    assert "repo_scan" in profiles[config.model_roles["fast"]].preferred_for
    assert profiles[config.model_roles["coding"]].cost_tier == "high"
    assert "code_patch" in profiles[config.model_roles["coding"]].preferred_for


def test_setup_command_writes_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--provider-id",
            "main",
            "--base-url",
            "https://example.com/v1",
            "--api-key-env",
            "MAIN_API_KEY",
            "--model",
            "general",
            "--fast-model",
            "fast",
            "--planning-model",
            "planner",
            "--coding-model",
            "coder",
            "--review-model",
            "reviewer",
            "--coding-daily-limit",
            "10",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.providers[0].base_url == "https://example.com/v1"
    assert config.model_roles["coding"] == "main:coder"
    assert config.quota_policies[0].id == "coding_daily"


def test_setup_command_writes_token_quota_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--provider-id",
            "main",
            "--base-url",
            "https://example.com/v1",
            "--api-key-env",
            "MAIN_API_KEY",
            "--model",
            "general",
            "--coding-model",
            "coder",
            "--coding-daily-token-limit",
            "80000",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.quota_policies[0].id == "coding_daily_tokens"
    assert config.quota_policies[0].unit == "token"
    assert config.quota_policies[0].windows[0].limit == 80_000


def test_setup_command_reports_conflicting_quota_units(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--provider-id",
            "main",
            "--base-url",
            "https://example.com/v1",
            "--api-key-env",
            "MAIN_API_KEY",
            "--model",
            "general",
            "--coding-model",
            "coder",
            "--coding-daily-limit",
            "10",
            "--coding-daily-token-limit",
            "80000",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code != 0
    assert "--coding-daily-limit" in result.output


def test_setup_command_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("permission_mode: suggest\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--base-url",
            "https://example.com/v1",
            "--model",
            "general",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 1
    assert "Config already exists" in result.output
