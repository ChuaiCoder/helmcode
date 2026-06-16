from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ModelResponse(BaseModel):
    content: str
    raw: dict[str, object] = Field(default_factory=dict)


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
