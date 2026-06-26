from pathlib import Path

from helmcode.agent.executor import Executor
from helmcode.core.exceptions import PermissionDenied
from helmcode.memory.hooks import HookStore
from helmcode.memory.session_store import SessionStore
from helmcode.tools.base import ToolResult


class FakeTestsTool:
    def __init__(self, result: ToolResult) -> None:
        self.result = result

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        return self.result


def test_executor_preserves_failed_test_status(tmp_path: Path) -> None:
    executor = Executor(root_path=tmp_path, permission_mode="edit")
    executor.tests_tool = FakeTestsTool(ToolResult(ok=False, content="failed", data={"returncode": 1}))

    result = executor.run_tests()

    assert result.ok is False
    assert result.output == "failed"


def test_executor_required_pre_tool_hook_blocks_patch_write(tmp_path: Path) -> None:
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    HookStore(tmp_path).add(
        event="PreToolUse",
        command='python -c "import sys; print(\'blocked write\'); sys.exit(5)"',
        hook_id="block-write",
        required=True,
    )
    store = SessionStore(tmp_path)
    executor = Executor(
        root_path=tmp_path,
        permission_mode="edit",
        session_store=store,
        session_id="session-a",
    )

    try:
        executor.prepare_patch(patch)
    except PermissionDenied as exc:
        assert "required hook failed: block-write" in str(exc)
    else:
        raise AssertionError("required PreToolUse hook should block write_patch")

    assert not (tmp_path / ".helmcode" / "pending.patch").exists()
    hook_events = [
        event.payload
        for event in store.list_events("session-a")
        if event.event_type == "hook_result"
    ]
    assert hook_events[0]["event"] == "PreToolUse"
    assert hook_events[0]["ok"] is False
