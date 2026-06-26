from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ModelResponse(BaseModel):
    content: str
    raw: dict[str, object] = Field(default_factory=dict)

    @property
    def usage(self) -> dict[str, int]:
        return extract_usage(self.raw)


class ModelInfo(BaseModel):
    id: str
    provider_id: str
    raw: dict[str, object] = Field(default_factory=dict)


class ProviderAdapter(ABC):
    id: str

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    @abstractmethod
    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        raise NotImplementedError

    async def list_models_async(self) -> list[ModelInfo]:
        return self.list_models()

    async def chat_async(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        return self.chat(model, messages)


def extract_usage(raw: dict[str, object]) -> dict[str, int]:
    usage = _as_dict(raw.get("usage"))
    if usage is None:
        return {}
    prompt_details = _as_dict(usage.get("prompt_tokens_details")) or {}
    completion_details = _as_dict(usage.get("completion_tokens_details")) or {}
    prompt_tokens = _first_int(usage, "prompt_tokens", "input_tokens")
    completion_tokens = _first_int(usage, "completion_tokens", "output_tokens")
    total_tokens = _first_int(usage, "total_tokens")
    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    cached_tokens = _first_int(
        usage,
        "cached_tokens",
        "prompt_cache_hit_tokens",
        "cache_read_input_tokens",
    )
    if cached_tokens is None:
        cached_tokens = _first_int(prompt_details, "cached_tokens")
    cache_miss_tokens = _first_int(
        usage,
        "prompt_cache_miss_tokens",
        "cache_creation_input_tokens",
    )
    if cache_miss_tokens is None:
        cache_miss_tokens = _first_int(prompt_details, "cache_miss_tokens")
    reasoning_tokens = _first_int(completion_details, "reasoning_tokens")

    result: dict[str, int] = {}
    for key, value in [
        ("prompt_tokens", prompt_tokens),
        ("completion_tokens", completion_tokens),
        ("total_tokens", total_tokens),
        ("cached_tokens", cached_tokens),
        ("cache_miss_tokens", cache_miss_tokens),
        ("reasoning_tokens", reasoning_tokens),
    ]:
        if value is not None:
            result[key] = value
    return result


def _as_dict(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _first_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                continue
    return None
