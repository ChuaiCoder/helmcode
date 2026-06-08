from pathlib import Path

from helmcode.agent.runner import RunOrchestrator
from helmcode.context.workspace import Workspace
from helmcode.models.provider import ChatMessage, ModelResponse


class SequenceProvider:
    def __init__(self, patch: str) -> None:
        self.patch = patch
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        self.calls.append((model, messages))
        if model == "fake:planning":
            return ModelResponse(content="PLAN:\n1. Update hello.txt.\n2. Run pytest.")
        return ModelResponse(content=self.patch)


class RecordingExecutor:
    def __init__(self) -> None:
        self.tests_run = 0

    def run_tests(self, command: str | None = None) -> str:
        self.tests_run += 1
        return "tests passed"


class SequencedPatchProvider:
    def __init__(self, patches: list[str]) -> None:
        self.patches = patches
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        self.calls.append((model, messages))
        if model == "fake:planning":
            return ModelResponse(content="PLAN:\n1. Update hello.txt.\n2. Run pytest.")
        return ModelResponse(content=self.patches.pop(0))


class SequencedExecutor:
    def __init__(self, outputs: list[tuple[bool, str]]) -> None:
        self.outputs = outputs
        self.tests_run = 0

    def run_tests(self, command: str | None = None):
        self.tests_run += 1
        ok, output = self.outputs.pop(0)
        return ok, output


def test_plan_does_not_call_coding_provider(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.discover(tmp_path)
    planning_provider = SequenceProvider(patch="not a patch")
    coding_provider = SequenceProvider(patch="not called")
    runner = RunOrchestrator(
        workspace=workspace,
        provider=planning_provider,
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        coding_provider=coding_provider,
    )

    plan_state = runner.plan("update greeting")

    assert "Update hello.txt" in plan_state.plan
    assert len(planning_provider.calls) == 1
    assert coding_provider.calls == []


def test_confirmed_run_applies_patch_and_runs_tests(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    executor = RecordingExecutor()
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider(patch),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="edit",
        executor=executor,
    )

    result = runner.run("update greeting", confirmed=True, run_tests=True)

    assert result.applied_files == ["hello.txt"]
    assert result.test_output == "tests passed"
    assert executor.tests_run == 1
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello world\n"


def test_unconfirmed_run_stores_patch_without_applying(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider(patch),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
    )

    result = runner.run("update greeting", confirmed=False, run_tests=True)

    assert result.applied_files == []
    assert result.test_output is None
    assert result.pending_patch == patch
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello\n"


def test_apply_prepared_result_does_not_call_model_again(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    provider = SequenceProvider(patch)
    workspace = Workspace.discover(tmp_path)
    executor = RecordingExecutor()
    runner = RunOrchestrator(
        workspace=workspace,
        provider=provider,
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="edit",
        executor=executor,
    )

    prepared = runner.prepare("update greeting")
    call_count_before_apply = len(provider.calls)
    applied = runner.apply_prepared(prepared, run_tests=True)

    assert len(provider.calls) == call_count_before_apply
    assert applied.applied_files == ["hello.txt"]
    assert applied.test_output == "tests passed"
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello world\n"


def test_apply_prepared_removes_pending_patch_file(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider(patch),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="edit",
        executor=RecordingExecutor(),
    )

    prepared = runner.prepare("update greeting")
    pending_patch_path = tmp_path / ".helmcode" / "pending.patch"

    assert pending_patch_path.exists()

    runner.apply_prepared(prepared, run_tests=False)

    assert not pending_patch_path.exists()


def test_runner_can_use_separate_coding_provider(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    planning_provider = SequenceProvider(patch="not a patch")
    coding_provider = SequenceProvider(patch=patch)
    runner = RunOrchestrator(
        workspace=workspace,
        provider=planning_provider,
        planning_model_id="fake:planning",
        coding_model_id="other:coding",
        permission_mode="suggest",
        coding_provider=coding_provider,
    )

    prepared = runner.prepare("update greeting")

    assert prepared.patch_files == ["hello.txt"]
    assert len(planning_provider.calls) == 1
    assert coding_provider.calls[-1][0] == "other:coding"


def test_apply_prepared_repairs_after_failed_tests(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    first_patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+broken
"""
    repair_patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-broken
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    executor = SequencedExecutor(outputs=[(False, "assert broken"), (True, "tests passed")])
    provider = SequencedPatchProvider([first_patch, repair_patch])
    runner = RunOrchestrator(
        workspace=workspace,
        provider=provider,
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="edit",
        executor=executor,
    )

    result = runner.run("update greeting", confirmed=True, run_tests=True)

    assert result.applied_files == ["hello.txt", "hello.txt"]
    assert result.test_output == "tests passed"
    assert result.repair_attempts == 1
    assert executor.tests_run == 2
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello world\n"
    assert "assert broken" in provider.calls[-1][1][-1].content


def test_apply_prepared_does_not_repair_when_tests_pass(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    executor = SequencedExecutor(outputs=[(True, "tests passed")])
    provider = SequencedPatchProvider([patch])
    runner = RunOrchestrator(
        workspace=workspace,
        provider=provider,
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="edit",
        executor=executor,
    )

    result = runner.run("update greeting", confirmed=True, run_tests=True)

    assert result.repair_attempts == 0
    assert len(provider.calls) == 2
    assert result.test_output == "tests passed"


def test_apply_prepared_stops_after_max_repair_attempts(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("0\n", encoding="utf-8")
    patches = [
        """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-0
+1
""",
        """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-1
+2
""",
        """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-2
+3
""",
        """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-3
+4
""",
    ]
    workspace = Workspace.discover(tmp_path)
    executor = SequencedExecutor(
        outputs=[
            (False, "fail 1"),
            (False, "fail 2"),
            (False, "fail 3"),
            (False, "fail 4"),
        ]
    )
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequencedPatchProvider(patches),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="edit",
        executor=executor,
        max_repair_attempts=3,
    )

    result = runner.run("increment", confirmed=True, run_tests=True)

    assert result.repair_attempts == 3
    assert result.test_output == "fail 4"
    assert executor.tests_run == 4
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "4\n"
