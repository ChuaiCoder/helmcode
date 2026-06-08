from __future__ import annotations

from helmcode.agent.prompts import CODING_SYSTEM_PROMPT
from helmcode.context.context_builder import ContextBuilder
from helmcode.context.workspace import Workspace
from helmcode.models.provider import ChatMessage, ModelResponse, ProviderAdapter


class Coder:
    def __init__(self, workspace: Workspace, provider: ProviderAdapter, model_id: str) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model_id = model_id

    def create_patch(self, task: str, plan: str) -> ModelResponse:
        built_context = ContextBuilder(self.workspace).build_for_task(task)
        messages = [
            ChatMessage(role="system", content=CODING_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"{built_context.text}\n\n"
                    f"Approved plan:\n{plan}\n\n"
                    "Return a unified diff patch only."
                ),
            ),
        ]
        return self.provider.chat(self.model_id, messages)
