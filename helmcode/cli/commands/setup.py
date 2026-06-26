from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from helmcode.core.config import (
    HelmcodeConfig,
    ModelProfileConfig,
    ProviderConfig,
    QuotaPolicyConfig,
    QuotaWindowConfig,
    save_user_config,
    user_config_path,
)
from helmcode.core.constants import (
    MODEL_ROLE_CODING,
    MODEL_ROLE_DEFAULT,
    MODEL_ROLE_FAST,
    MODEL_ROLE_PLANNING,
    MODEL_ROLE_REVIEW,
)
from helmcode.models.quota import (
    TASK_CLASSIFY,
    TASK_CODE_PATCH,
    TASK_PLAN,
    TASK_REPAIR,
    TASK_REPO_SCAN,
    TASK_REVIEW,
    TASK_SUMMARIZE,
)

console = Console()


def setup_cmd(
    provider_id: str = typer.Option("main_pool", "--provider-id", help="Provider id."),
    base_url: str | None = typer.Option(None, "--base-url", help="OpenAI-compatible base URL."),
    api_key_env: str = typer.Option("MAIN_POOL_API_KEY", "--api-key-env", help="API key env var."),
    model: str | None = typer.Option(None, "--model", help="Default model name."),
    fast_model: str | None = typer.Option(None, "--fast-model", help="Cheap fast model name."),
    planning_model: str | None = typer.Option(None, "--planning-model", help="Planning model name."),
    coding_model: str | None = typer.Option(None, "--coding-model", help="Coding model name."),
    review_model: str | None = typer.Option(None, "--review-model", help="Review model name."),
    permission_mode: str = typer.Option("suggest", "--permission", help="read_only, suggest, edit, or auto."),
    routing_mode: str = typer.Option("quota", "--routing", help="fixed, quota, or recommend."),
    fast_daily_limit: int | None = typer.Option(None, "--fast-daily-limit", min=1),
    planning_daily_limit: int | None = typer.Option(None, "--planning-daily-limit", min=1),
    coding_daily_limit: int | None = typer.Option(None, "--coding-daily-limit", min=1),
    review_daily_limit: int | None = typer.Option(None, "--review-daily-limit", min=1),
    config_path: Path | None = typer.Option(None, "--config", help="Write this config path."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing config."),
) -> None:
    """Create a usable user config for provider, model roles, profiles, and quotas."""
    target = config_path or user_config_path()
    if target.exists() and not force:
        console.print(f"[yellow]Config already exists:[/yellow] {target}")
        console.print("Use --force to overwrite it.")
        raise typer.Exit(1)

    base_url = base_url or typer.prompt("OpenAI-compatible base URL", default="https://example.com/v1")
    model = model or typer.prompt("Default model")
    fast_model = fast_model or model
    planning_model = planning_model or model
    coding_model = coding_model or model
    review_model = review_model or planning_model

    config = build_setup_config(
        provider_id=provider_id,
        base_url=base_url,
        api_key_env=api_key_env,
        model=model,
        fast_model=fast_model,
        planning_model=planning_model,
        coding_model=coding_model,
        review_model=review_model,
        permission_mode=permission_mode,
        routing_mode=routing_mode,
        fast_daily_limit=fast_daily_limit,
        planning_daily_limit=planning_daily_limit,
        coding_daily_limit=coding_daily_limit,
        review_daily_limit=review_daily_limit,
    )
    path = save_user_config(config, target)
    console.print(f"Wrote helmcode config: {path}")
    console.print(f"Set API key before running model commands: {api_key_env}=...")


def build_setup_config(
    *,
    provider_id: str,
    base_url: str,
    api_key_env: str,
    model: str,
    fast_model: str,
    planning_model: str,
    coding_model: str,
    review_model: str,
    permission_mode: str,
    routing_mode: str,
    fast_daily_limit: int | None = None,
    planning_daily_limit: int | None = None,
    coding_daily_limit: int | None = None,
    review_daily_limit: int | None = None,
) -> HelmcodeConfig:
    model_roles = {
        MODEL_ROLE_DEFAULT: _model_id(provider_id, model),
        MODEL_ROLE_FAST: _model_id(provider_id, fast_model),
        MODEL_ROLE_PLANNING: _model_id(provider_id, planning_model),
        MODEL_ROLE_CODING: _model_id(provider_id, coding_model),
        MODEL_ROLE_REVIEW: _model_id(provider_id, review_model),
    }
    return HelmcodeConfig(
        permission_mode=permission_mode,
        routing_mode=routing_mode,
        providers=[
            ProviderConfig(
                id=provider_id,
                type="openai_compatible",
                base_url=base_url,
                api_key_env=api_key_env,
            )
        ],
        model_roles=model_roles,
        model_profiles=_build_model_profiles(model_roles),
        quota_policies=_build_quota_policies(
            model_roles=model_roles,
            fast_daily_limit=fast_daily_limit,
            planning_daily_limit=planning_daily_limit,
            coding_daily_limit=coding_daily_limit,
            review_daily_limit=review_daily_limit,
        ),
    )


def _build_model_profiles(model_roles: dict[str, str]) -> list[ModelProfileConfig]:
    profiles: dict[str, ModelProfileConfig] = {}

    def upsert(model_id: str, labels: list[str], preferred_for: list[str], cost_tier: str) -> None:
        existing = profiles.get(model_id)
        if existing is None:
            profiles[model_id] = ModelProfileConfig(
                id=model_id,
                labels=labels,
                preferred_for=preferred_for,
                cost_tier=cost_tier,
            )
            return
        existing.labels = _dedupe([*existing.labels, *labels])
        existing.preferred_for = _dedupe([*existing.preferred_for, *preferred_for])
        existing.cost_tier = _max_cost(existing.cost_tier, cost_tier)

    upsert(
        model_roles[MODEL_ROLE_FAST],
        ["fast", "cheap"],
        [TASK_CLASSIFY, TASK_REPO_SCAN, TASK_SUMMARIZE],
        "low",
    )
    upsert(model_roles[MODEL_ROLE_PLANNING], ["planning"], [TASK_PLAN], "medium")
    upsert(model_roles[MODEL_ROLE_CODING], ["coding"], [TASK_CODE_PATCH, TASK_REPAIR], "high")
    upsert(model_roles[MODEL_ROLE_REVIEW], ["review"], [TASK_REVIEW], "medium")
    return list(profiles.values())


def _build_quota_policies(
    *,
    model_roles: dict[str, str],
    fast_daily_limit: int | None,
    planning_daily_limit: int | None,
    coding_daily_limit: int | None,
    review_daily_limit: int | None,
) -> list[QuotaPolicyConfig]:
    policies: list[QuotaPolicyConfig] = []
    for role, limit in [
        (MODEL_ROLE_FAST, fast_daily_limit),
        (MODEL_ROLE_PLANNING, planning_daily_limit),
        (MODEL_ROLE_CODING, coding_daily_limit),
        (MODEL_ROLE_REVIEW, review_daily_limit),
    ]:
        if limit is None:
            continue
        policies.append(
            QuotaPolicyConfig(
                id=f"{role}_daily",
                model_patterns=[model_roles[role]],
                unit="request",
                windows=[QuotaWindowConfig(name="daily", type="calendar_day", limit=limit)],
            )
        )
    return policies


def _model_id(provider_id: str, model: str) -> str:
    return model if ":" in model else f"{provider_id}:{model}"


def _max_cost(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    return left if order[left] >= order[right] else right


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
