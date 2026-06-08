from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TokenBudget:
    max_chars: int = 32_000

    def fit(self, sections: list[str]) -> str:
        output: list[str] = []
        used = 0
        for section in sections:
            remaining = self.max_chars - used
            if remaining <= 0:
                break
            if len(section) > remaining:
                output.append(section[:remaining] + "\n[truncated]")
                break
            output.append(section)
            used += len(section)
        return "\n\n".join(output)
