from __future__ import annotations

import os

import httpx

from helmcode.core.config import ProviderConfig
from helmcode.core.exceptions import ModelError
from helmcode.models.provider import ChatMessage, ModelInfo, ModelResponse, ProviderAdapter


class OpenAICompatibleProvider(ProviderAdapter):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.id = config.id

    @property
    def _headers(self) -> dict[str, str]:
        api_key = os.getenv(self.config.api_key_env)
        if not api_key:
            raise ModelError(f"Missing API key env var: {self.config.api_key_env}")
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def list_models(self) -> list[ModelInfo]:
        url = self.config.base_url.rstrip("/") + "/models"
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.get(url, headers=self._headers)
            response.raise_for_status()
        payload = response.json()
        items = payload.get("data", payload if isinstance(payload, list) else [])
        return [
            ModelInfo(id=f"{self.id}:{item['id']}", provider_id=self.id, raw=item)
            for item in items
            if isinstance(item, dict) and item.get("id")
        ]

    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        provider_prefix = f"{self.id}:"
        provider_model = model[len(provider_prefix) :] if model.startswith(provider_prefix) else model
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": provider_model,
            "messages": [message.model_dump() for message in messages],
        }
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(url, headers=self._headers, json=body)
            response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("Provider response did not include choices[0].message.content") from exc
        return ModelResponse(content=content, raw=payload)
