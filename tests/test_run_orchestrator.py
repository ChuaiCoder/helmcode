from pathlib import Path

from helmcode.agent.runtime import AgentRuntime
from helmcode.agent.runner import RunOrchestrator
from helmcode.context.workspace import Workspace
from helmcode.core.config import HelmcodeConfig, QuotaPolicyConfig, QuotaWindowConfig
from helmcode.core.exceptions import ModelError, PermissionDenied
from helmcode.models.quota import QuotaAwareSelector, QuotaLedger
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
    def __init__(self, root_path: Path | None = None) -> None:
        self.root_path = root_path
        self.tests_run = 0
        self.patches_prepared: list[str] = []
        self.patches_applied: list[str] = []

    def prepare_patch(self, patch: str) -> list[str]:
        self.patches_prepared.append(patch)
        if self.root_path:
            pending_dir = self.root_path / ".helmcode"
            pending_dir.mkdir(parents=True, exist_ok=True)
            (pending_dir / "pending.patch").write_text(patch, encoding="utf-8")
        return ["hello.txt"]

    def apply_patch(self, patch: str, confirmed: bool) -> list[str]:
        if not confirmed:
            return []
        self.patches_applied.append(patch)
        if self.root_path:
            self._simulate_apply(patch)
        return ["hello.txt"]

    def _simulate_apply(self, patch: str) -> None:
        if not self.root_path:
            return
        lines = patch.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("+") and not line.startswith("+++"):
                content = line[1:]
                if i + 1 < len(lines) and lines[i + 1].startswith("-"):
                    continue
                file_path = self.root_path / "hello.txt"
                if file_path.exists():
                    file_path.write_text(content + "\n", encoding="utf-8")
                    break

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
    def __init__(self, outputs: list[tuple[bool, str]], root_path: Path | None = None) -> None:
        self.outputs = outputs
        self.root_path = root_path
        self.tests_run = 0
        self.patches_prepared: list[str] = []
        self.patches_applied: list[str] = []

    def prepare_patch(self, patch: str) -> list[str]:
        self.patches_prepared.append(patch)
        if self.root_path:
            pending_dir = self.root_path / ".helmcode"
            pending_dir.mkdir(parents=True, exist_ok=True)
            (pending_dir / "pending.patch").write_text(patch, encoding="utf-8")
        return ["hello.txt"]

    def apply_patch(self, patch: str, confirmed: bool) -> list[str]:
        if not confirmed:
            return []
        self.patches_applied.append(patch)
        if self.root_path:
            self._simulate_apply(patch)
        return ["hello.txt"]

    def _simulate_apply(self, patch: str) -> None:
        if not self.root_path:
            return
        lines = patch.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("+") and not line.startswith("+++"):
                content = line[1:]
                if i + 1 < len(lines) and lines[i + 1].startswith("-"):
                    continue
                file_path = self.root_path / "hello.txt"
                if file_path.exists():
                    file_path.write_text(content + "\n", encoding="utf-8")
                    break

    def run_tests(self, command: str | None = None):
        self.tests_run += 1
        ok, output = self.outputs.pop(0)
        return ok, output


class ReviewProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        self.calls.append((model, messages))
        return ModelResponse(content=self.content)


class PreplanProvider:
    def __init__(self, patch: str) -> None:
        self.patch = patch
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def chat(self, model: str, messages: list[ChatMessage]) -> ModelResponse:
        self.calls.append((model, messages))
        if model == "fake:fast":
            if "summarizer agent" in messages[0].content:
                return ModelResponse(content="SUMMARY: hello.txt is the main change target")
            return ModelResponse(content="SCOUT: check hello.txt and pyproject.toml")
        if model == "fake:planning":
            return ModelResponse(content="PLAN:\n1. Update hello.txt.\n2. Run pytest.")
        return ModelResponse(content=self.patch)


class RecordingSessionStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def record(self, session_id: str, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((session_id, event_type, payload))


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
        permission_mode="edit",
        executor=RecordingExecutor(root_path=tmp_path),
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
    executor = RecordingExecutor(root_path=tmp_path)
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


def test_read_only_mode_allows_plan_but_blocks_patch_generation(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.discover(tmp_path)
    provider = SequenceProvider("not a patch")
    runner = RunOrchestrator(
        workspace=workspace,
        provider=provider,
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="read_only",
    )

    plan_state = runner.plan("update greeting")

    assert "Update hello.txt" in plan_state.plan
    try:
        runner.generate_patch_from_plan(plan_state)
    except PermissionDenied as exc:
        assert "read_only" in str(exc)
    else:
        raise AssertionError("read_only mode should block patch generation")
    assert len(provider.calls) == 1


def test_suggest_mode_blocks_confirmed_auto_apply(tmp_path: Path) -> None:
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

    prepared = runner.prepare("update greeting")

    try:
        runner.apply_prepared(prepared, run_tests=False)
    except PermissionDenied as exc:
        assert "suggest" in str(exc)
    else:
        raise AssertionError("suggest mode should block confirmed auto apply")
    assert prepared.pending_patch
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello\n"


def test_edit_mode_allows_confirmed_apply(tmp_path: Path) -> None:
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
        executor=RecordingExecutor(root_path=tmp_path),
    )

    prepared = runner.prepare("update greeting")
    result = runner.apply_prepared(prepared, run_tests=False)

    assert result.applied_files == ["hello.txt"]
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
    executor = RecordingExecutor(root_path=tmp_path)
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
        executor=RecordingExecutor(root_path=tmp_path),
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


def test_runner_runtime_records_model_calls_to_quota_ledger(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    config = HelmcodeConfig(
        model_roles={
            "default": "fake:planning",
            "planning": "fake:planning",
            "coding": "fake:coding",
            "review": "fake:review",
        }
    )
    runtime = AgentRuntime(
        workspace=workspace,
        selector=QuotaAwareSelector(config, ledger),
    )
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider(patch),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        runtime=runtime,
    )

    runner.prepare("update greeting")

    records = ledger.load()
    assert [(record.role, record.model_id) for record in records] == [
        ("planning", "fake:planning"),
        ("coding", "fake:coding"),
    ]


def test_runner_records_coding_plan_allocation_event(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    store = RecordingSessionStore()
    config = HelmcodeConfig(
        model_roles={
            "default": "fake:planning",
            "fast": "fake:fast",
            "planning": "fake:planning",
            "coding": "fake:coding",
            "review": "fake:review",
        }
    )
    runtime = AgentRuntime(
        workspace=workspace,
        selector=QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl")),
        session_store=store,
    )
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider(patch),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        runtime=runtime,
        session_store=store,
    )

    runner.prepare("add a greeting helper")

    allocation_events = [payload for _sid, event_type, payload in store.events if event_type == "task_allocated"]
    assert allocation_events
    assert allocation_events[0]["detected_task_type"] == "code_patch"
    assert [assignment["agent_id"] for assignment in allocation_events[0]["assignments"]] == [
        "planner",
        "coder",
    ]


def test_runner_executes_preplan_agents_and_injects_context(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    store = RecordingSessionStore()
    config = HelmcodeConfig(
        model_roles={
            "default": "fake:planning",
            "fast": "fake:fast",
            "planning": "fake:planning",
            "coding": "fake:coding",
            "review": "fake:review",
        }
    )
    runtime = AgentRuntime(
        workspace=workspace,
        selector=QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl")),
        session_store=store,
    )
    provider = PreplanProvider(patch)
    runner = RunOrchestrator(
        workspace=workspace,
        provider=provider,
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        runtime=runtime,
        session_store=store,
    )

    result = runner.plan("refactor the whole project architecture and implement a safer greeting helper")

    assert "Update hello.txt" in result.plan
    assert [model for model, _messages in provider.calls] == ["fake:fast", "fake:fast", "fake:planning"]
    planning_prompt = provider.calls[-1][1][1].content
    assert "Coding Plan pre-agent findings" in planning_prompt
    assert "SCOUT: check hello.txt and pyproject.toml" in planning_prompt
    assert "SUMMARY: hello.txt is the main change target" in planning_prompt
    completed = [payload for _sid, event_type, payload in store.events if event_type == "preplan_agent_completed"]
    assert [payload["agent_id"] for payload in completed] == ["scout", "summarizer"]
    called_models = [payload["model_id"] for _sid, event_type, payload in store.events if event_type == "model_called"]
    assert called_models == ["fake:fast", "fake:fast", "fake:planning"]


def test_runner_blocks_when_required_allocation_has_no_quota(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.discover(tmp_path)
    config = HelmcodeConfig(
        model_roles={
            "default": "fake:planning",
            "planning": "fake:planning",
            "coding": "fake:coding",
        },
        quota_policies=[
            QuotaPolicyConfig(
                id="coding_only",
                model_patterns=["fake:coding"],
                windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
            )
        ],
    )
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="fake:coding", role="coding", task_type="code_patch")
    runtime = AgentRuntime(
        workspace=workspace,
        selector=QuotaAwareSelector(config, ledger),
    )
    provider = SequenceProvider("not called")
    runner = RunOrchestrator(
        workspace=workspace,
        provider=provider,
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        runtime=runtime,
        block_on_allocation=True,
    )

    try:
        runner.plan("add a greeting helper")
    except ModelError as exc:
        assert "Coding Plan allocation blocked" in str(exc)
    else:
        raise AssertionError("required allocation exhaustion should block run planning")
    assert provider.calls == []


def test_runner_plan_mode_can_record_blocked_allocation_without_blocking(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.discover(tmp_path)
    store = RecordingSessionStore()
    config = HelmcodeConfig(
        model_roles={
            "default": "fake:planning",
            "planning": "fake:planning",
            "coding": "fake:coding",
        },
        quota_policies=[
            QuotaPolicyConfig(
                id="coding_only",
                model_patterns=["fake:coding"],
                windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
            )
        ],
    )
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="fake:coding", role="coding", task_type="code_patch")
    runtime = AgentRuntime(
        workspace=workspace,
        selector=QuotaAwareSelector(config, ledger),
        session_store=store,
    )
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider("not a patch"),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        runtime=runtime,
        session_store=store,
        block_on_allocation=False,
    )

    result = runner.plan("add a greeting helper")

    assert "Update hello.txt" in result.plan
    allocation_events = [payload for _sid, event_type, payload in store.events if event_type == "task_allocated"]
    assert allocation_events[0]["blocked"] is True


def test_runner_plan_mode_still_blocks_exhausted_planning_call(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    workspace = Workspace.discover(tmp_path)
    store = RecordingSessionStore()
    config = HelmcodeConfig(
        model_roles={
            "default": "fake:planning",
            "planning": "fake:planning",
            "coding": "fake:coding",
        },
        quota_policies=[
            QuotaPolicyConfig(
                id="planning_only",
                model_patterns=["fake:planning"],
                windows=[QuotaWindowConfig(name="rolling", type="rolling", duration_seconds=300, limit=1)],
            )
        ],
    )
    ledger = QuotaLedger(tmp_path / "quota.jsonl")
    ledger.record(model_id="fake:planning", role="planning", task_type="plan")
    runtime = AgentRuntime(
        workspace=workspace,
        selector=QuotaAwareSelector(config, ledger),
        session_store=store,
    )
    provider = SequenceProvider("not called")
    runner = RunOrchestrator(
        workspace=workspace,
        provider=provider,
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        runtime=runtime,
        session_store=store,
        block_on_allocation=False,
    )

    try:
        runner.plan("plan a greeting helper")
    except ModelError as exc:
        assert "No quota capacity for planning/plan" in str(exc)
    else:
        raise AssertionError("exhausted planning quota should block the real provider call")
    assert provider.calls == []
    blocked = [payload for _sid, event_type, payload in store.events if event_type == "model_blocked"]
    assert blocked[0]["model_id"] == "fake:planning"


def test_generate_patch_reviews_patch_when_review_model_is_configured(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    review_provider = ReviewProvider("LGTM: tests should pass")
    store = RecordingSessionStore()
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider(patch),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        review_provider=review_provider,
        review_model_id="fake:review",
        session_store=store,
    )

    prepared = runner.prepare("update greeting")

    assert prepared.review == "LGTM: tests should pass"
    assert review_provider.calls[-1][0] == "fake:review"
    assert patch in review_provider.calls[-1][1][-1].content
    assert any(event_type == "patch_reviewed" for _sid, event_type, _payload in store.events)


def test_generate_patch_skips_review_when_review_model_is_not_configured(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    review_provider = ReviewProvider("should not be called")
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider(patch),
        planning_model_id="fake:planning",
        coding_model_id="fake:coding",
        permission_mode="suggest",
        review_provider=review_provider,
    )

    prepared = runner.prepare("update greeting")

    assert prepared.review is None
    assert review_provider.calls == []


def test_generate_patch_can_use_separate_review_provider(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    workspace = Workspace.discover(tmp_path)
    coding_provider = SequenceProvider(patch)
    review_provider = ReviewProvider("reviewed by separate provider")
    runner = RunOrchestrator(
        workspace=workspace,
        provider=SequenceProvider("not used for patch"),
        planning_model_id="fake:planning",
        coding_model_id="coding:model",
        permission_mode="suggest",
        coding_provider=coding_provider,
        review_provider=review_provider,
        review_model_id="review:model",
    )

    prepared = runner.prepare("update greeting")

    assert prepared.review == "reviewed by separate provider"
    assert coding_provider.calls[-1][0] == "coding:model"
    assert review_provider.calls[-1][0] == "review:model"


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
    executor = SequencedExecutor(outputs=[(False, "assert broken"), (True, "tests passed")], root_path=tmp_path)
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
    executor = SequencedExecutor(outputs=[(True, "tests passed")], root_path=tmp_path)
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
        ],
        root_path=tmp_path,
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
