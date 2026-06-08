from pathlib import Path

from helmcode.agent.loop import AgentLoop
from helmcode.agent.state import AgentState
from helmcode.context.workspace import Workspace
from helmcode.models.provider import ChatMessage, ModelResponse


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []
        self.models: list[str] = []

    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        self.models.append(model)
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


class PatchProvider:
    def __init__(self, patch: str) -> None:
        self.patch = patch
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        self.calls.append((model, messages))
        if model == "fake:planning":
            return ModelResponse(content="PLAN:\n1. Update hello.txt.\n2. Run tests.")
        return ModelResponse(content=self.patch)


def test_agent_generate_patch_uses_coding_model_and_does_not_apply(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.discover(tmp_path)
    state = AgentState.start(workspace_path=workspace.root_path, user_task="update greeting")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    provider = PatchProvider(patch)
    agent = AgentLoop(
        workspace=workspace,
        model_provider=provider,
        model_id="fake:planning",
        state=state,
        coding_model_id="fake:coding",
    )

    result = agent.generate_patch("update greeting")

    assert result.files == ["hello.txt"]
    assert state.pending_patch == patch
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello\n"
    assert provider.calls[-1][0] == "fake:coding"


def test_agent_generate_patch_can_use_separate_coding_provider(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.discover(tmp_path)
    state = AgentState.start(workspace_path=workspace.root_path, user_task="update greeting")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    planning_provider = PatchProvider(patch="not a patch")
    coding_provider = PatchProvider(patch=patch)
    agent = AgentLoop(
        workspace=workspace,
        model_provider=planning_provider,
        model_id="fake:planning",
        state=state,
        coding_model_id="other:coding",
        coding_provider=coding_provider,
    )

    result = agent.generate_patch("update greeting")

    assert result.files == ["hello.txt"]
    assert len(planning_provider.calls) == 1
    assert coding_provider.calls[-1][0] == "other:coding"
