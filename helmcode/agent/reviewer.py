from __future__ import annotations

from helmcode.agent.prompts import REVIEW_SYSTEM_PROMPT
from helmcode.models.provider import ChatMessage, ModelResponse, ProviderAdapter


class Reviewer:
    def __init__(self, provider: ProviderAdapter, model_id: str) -> None:
        self.provider = provider
        self.model_id = model_id

    def review_patch(self, patch: str) -> ModelResponse:
        messages = [
            ChatMessage(role="system", content=REVIEW_SYSTEM_PROMPT),
            ChatMessage(role="user", content=patch),
        ]
        return self.provider.chat(self.model_id, messages)
