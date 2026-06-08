from __future__ import annotations

from dataclasses import dataclass, field

from helmcode.core.config import HelmcodeConfig
from helmcode.core.exceptions import ConfigError, ModelError
from helmcode.models.openai_compatible import OpenAICompatibleProvider
from helmcode.models.provider import ModelInfo, ProviderAdapter


@dataclass(slots=True)
class ModelRegistry:
    providers: dict[str, ProviderAdapter] = field(default_factory=dict)
    models: dict[str, ModelInfo] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: HelmcodeConfig) -> "ModelRegistry":
        registry = cls()
        for provider_config in config.providers:
            if provider_config.type != "openai_compatible":
                raise ConfigError(f"Unsupported provider type: {provider_config.type}")
            registry.providers[provider_config.id] = OpenAICompatibleProvider(provider_config)
        return registry

    def provider_for_model(self, model_id: str) -> ProviderAdapter:
        provider_id = model_id.split(":", 1)[0]
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            raise ModelError(f"No provider configured for model id: {model_id}") from exc

    def sync(self) -> list[ModelInfo]:
        synced: list[ModelInfo] = []
        for provider in self.providers.values():
            synced.extend(provider.list_models())
        self.models = {model.id: model for model in synced}
        return synced
