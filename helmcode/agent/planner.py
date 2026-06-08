from __future__ import annotations

from helmcode.agent.prompts import PLANNER_SYSTEM_PROMPT
from helmcode.context.context_builder import ContextBuilder
from helmcode.context.workspace import Workspace
from helmcode.models.provider import ChatMessage, ModelResponse, ProviderAdapter


class Planner:
    def __init__(self, workspace: Workspace, provider: ProviderAdapter, model_id: str) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model_id = model_id

    def create_plan(self, task: str) -> ModelResponse:
        built_context = ContextBuilder(self.workspace).build_for_task(task)
        messages = [
            ChatMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=built_context.text),
        ]
        return self.provider.chat(self.model_id, messages)
