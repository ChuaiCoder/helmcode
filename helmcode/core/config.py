from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from helmcode.core.constants import DEFAULT_PERMISSION_MODE
from helmcode.core.exceptions import ConfigError

PermissionMode = Literal["read_only", "suggest", "edit", "auto"]
RoutingMode = Literal["fixed", "quota", "recommend"]
QuotaUnit = Literal["request", "prompt_call", "token", "lane", "credit"]
QuotaWindowType = Literal["rolling", "calendar_day", "calendar_week", "calendar_month"]
CostTier = Literal["low", "medium", "high"]
McpTransport = Literal["stdio", "http", "sse"]


class ProviderConfig(BaseModel):
    id: str
    type: str = "openai_compatible"
    base_url: str
    api_key_env: str
    timeout_seconds: float = 60.0

    @property
    def has_api_key(self) -> bool:
        return bool(os.getenv(self.api_key_env))


class ModelProfileConfig(BaseModel):
    id: str
    labels: list[str] = Field(default_factory=list)
    preferred_for: list[str] = Field(default_factory=list)
    cost_tier: CostTier = "medium"
    fallback_models: list[str] = Field(default_factory=list)


class QuotaWindowConfig(BaseModel):
    name: str
    type: QuotaWindowType
    limit: int = Field(gt=0)
    duration_seconds: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_window(self) -> "QuotaWindowConfig":
        if self.type == "rolling" and self.duration_seconds is None:
            raise ValueError("rolling quota windows require duration_seconds")
        if self.type != "rolling" and self.duration_seconds is not None:
            raise ValueError("duration_seconds is only valid for rolling quota windows")
        return self


class QuotaPolicyConfig(BaseModel):
    id: str
    model_patterns: list[str] = Field(default_factory=list)
    unit: QuotaUnit = "request"
    windows: list[QuotaWindowConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_policy(self) -> "QuotaPolicyConfig":
        if not self.model_patterns:
            raise ValueError("quota policies require at least one model pattern")
        if not self.windows:
            raise ValueError("quota policies require at least one window")
        return self


class AgentProfileConfig(BaseModel):
    id: str
    role: str
    task_type: str
    model_role: str
    purpose: str
    order: int = 100
    required: bool = True
    triggers: list[str] = Field(default_factory=list)
    estimated_tokens: int | None = Field(default=None, gt=0)


class McpServerConfig(BaseModel):
    id: str
    transport: McpTransport = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True
    description: str = ""

    @model_validator(mode="after")
    def validate_server(self) -> "McpServerConfig":
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP servers require command")
        if self.transport in {"http", "sse"} and not self.url:
            raise ValueError("http/sse MCP servers require url")
        return self


class HelmcodeConfig(BaseModel):
    permission_mode: PermissionMode = DEFAULT_PERMISSION_MODE
    routing_mode: RoutingMode = "quota"
    providers: list[ProviderConfig] = Field(default_factory=list)
    model_roles: dict[str, str] = Field(default_factory=dict)
    model_profiles: list[ModelProfileConfig] = Field(default_factory=list)
    quota_policies: list[QuotaPolicyConfig] = Field(default_factory=list)
    agent_profiles: list[AgentProfileConfig] = Field(default_factory=list)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    shell_timeout_seconds: int = 120
    max_read_chars: int = 20_000


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "default_config.yaml"


def user_config_path() -> Path:
    return Path.home() / ".helmcode" / "config.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file must contain a mapping: {path}")
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Path | None = None) -> HelmcodeConfig:
    raw = load_yaml(default_config_path())
    selected_user_path = config_path or user_config_path()
    raw = deep_merge(raw, load_yaml(selected_user_path))
    try:
        return HelmcodeConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def save_user_config(config: HelmcodeConfig, path: Path | None = None) -> Path:
    target = path or user_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json", exclude_none=True)
    with target.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False)
    return target
