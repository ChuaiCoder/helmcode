from pathlib import Path

from helmcode.agent.loop import AgentLoop
from helmcode.agent.state import AgentState
from helmcode.context.workspace import Workspace
from helmcode.models.provider import ChatMessage, ModelResponse


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        self.calls.append(messages)
        return ModelResponse(
            content=(
                "PLAN:\n"
                "1. Inspect relevant files.\n"
                "2. Prepare a patch if the user confirms.\n"
            )
        )


def test_agent_plan_does_not_apply_patch(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    workspace = Workspace.discover(tmp_path)
    state = AgentState.start(workspace_path=workspace.root_path, user_task="add tests")
    provider = FakeProvider()
    agent = AgentLoop(workspace=workspace, model_provider=provider, model_id="fake:model", state=state)

    plan = agent.plan("add tests")

    assert "Inspect relevant files" in plan.content
    assert state.plan is not None
    assert state.pending_patch is None
    assert not state.patches_applied
