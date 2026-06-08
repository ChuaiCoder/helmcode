from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from helmcode.core.constants import DEFAULT_PERMISSION_MODE
from helmcode.core.exceptions import ConfigError

PermissionMode = Literal["read_only", "suggest", "edit", "auto"]


class ProviderConfig(BaseModel):
    id: str
    type: str = "openai_compatible"
    base_url: str
    api_key_env: str
    timeout_seconds: float = 60.0

    @property
    def has_api_key(self) -> bool:
        return bool(os.getenv(self.api_key_env))


class HelmcodeConfig(BaseModel):
    permission_mode: PermissionMode = DEFAULT_PERMISSION_MODE
    providers: list[ProviderConfig] = Field(default_factory=list)
    model_roles: dict[str, str] = Field(default_factory=dict)
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
