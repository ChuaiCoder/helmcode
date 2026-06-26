from __future__ import annotations

from helmcode.cli.commands.keys import build_key_status
from helmcode.core.config import HelmcodeConfig, ProviderConfig


def test_build_key_status_reports_env_without_secret(monkeypatch) -> None:
    monkeypatch.setenv("MAIN_POOL_API_KEY", "secret-value")
    config = HelmcodeConfig(
        providers=[
            ProviderConfig(
                id="main_pool",
                base_url="https://example.com/v1",
                api_key_env="MAIN_POOL_API_KEY",
            )
        ],
        model_roles={
            "planning": "main_pool:planner",
            "coding": "main_pool:coder",
            "review": "other_pool:reviewer",
        },
    )

    statuses = build_key_status(config)

    assert len(statuses) == 1
    assert statuses[0].provider_id == "main_pool"
    assert statuses[0].api_key_env == "MAIN_POOL_API_KEY"
    assert statuses[0].is_set is True
    assert statuses[0].roles == ["coding", "planning"]
    assert "secret-value" not in str(statuses[0].to_dict())


def test_build_key_status_reports_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_POOL_API_KEY", raising=False)
    config = HelmcodeConfig(
        providers=[
            ProviderConfig(
                id="missing_pool",
                base_url="https://example.com/v1",
                api_key_env="MISSING_POOL_API_KEY",
            )
        ]
    )

    statuses = build_key_status(config)

    assert statuses[0].is_set is False
    assert statuses[0].roles == []
