from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from helmcode.safety.risk import RiskLevel


class ToolResult(BaseModel):
    ok: bool
    content: str
    data: dict[str, Any] = {}


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]
    risk_level: ClassVar[RiskLevel] = RiskLevel.LOW

    @abstractmethod
    def run(self, raw_input: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def validate_input(self, raw_input: dict[str, Any]) -> BaseModel:
        return self.input_schema.model_validate(raw_input)
