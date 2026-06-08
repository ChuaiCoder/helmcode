from __future__ import annotations

from pydantic import BaseModel

from helmcode.tools.base import Tool, ToolResult


class DiagnosticsInput(BaseModel):
    output: str
    max_lines: int = 80


class DiagnosticsTool(Tool):
    name = "diagnostics"
    description = "Summarize lint, typecheck, build, or test output."
    input_schema = DiagnosticsInput

    def run(self, raw_input: dict[str, object]) -> ToolResult:
        params = self.validate_input(raw_input)
        assert isinstance(params, DiagnosticsInput)
        interesting = []
        for line in params.output.splitlines():
            lowered = line.lower()
            if any(token in lowered for token in ["error", "failed", "traceback", "assert", "exception"]):
                interesting.append(line)
            if len(interesting) >= params.max_lines:
                break
        content = "\n".join(interesting) if interesting else params.output[:4000]
        return ToolResult(ok=True, content=content, data={"line_count": len(interesting)})
