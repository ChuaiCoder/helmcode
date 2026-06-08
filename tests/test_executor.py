from pathlib import Path

from helmcode.agent.executor import Executor
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
