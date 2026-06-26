from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.cli.commands.setup import build_setup_config
from helmcode.core.config import load_config


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
