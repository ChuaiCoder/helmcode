from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False


@dataclass
class TokenBudget:
    max_tokens: int = 8000
    max_chars: int = 32_000  # fallback when tiktoken unavailable

    def __post_init__(self) -> None:
        self._encoding = _load_encoding()

    def _count_tokens(self, text: str) -> int:
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        return len(text)

    def fit(self, sections: list[str]) -> str:
        output: list[str] = []
        used_tokens = 0
        used_chars = 0

        for section in sections:
            section_tokens = self._count_tokens(section)
            section_chars = len(section)

            if self._encoding is not None:
                remaining_tokens = self.max_tokens - used_tokens
                if remaining_tokens <= 0:
                    break
                if section_tokens > remaining_tokens:
                    truncated = self._truncate_to_tokens(section, remaining_tokens)
                    output.append(truncated + "\n[truncated]")
                    break
            else:
                remaining_chars = self.max_chars - used_chars
                if remaining_chars <= 0:
                    break
                if section_chars > remaining_chars:
                    output.append(section[:remaining_chars] + "\n[truncated]")
                    break

            output.append(section)
            used_tokens += section_tokens
            used_chars += section_chars

        return "\n\n".join(output)

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        if self._encoding is None or max_tokens <= 0:
            return text[:self.max_chars] if max_tokens <= 0 else text

        tokens = self._encoding.encode(text)
        truncated_tokens = tokens[:max_tokens]
        return self._encoding.decode(truncated_tokens)

    @property
    def tokenizer_available(self) -> bool:
        return self._encoding is not None


@lru_cache(maxsize=1)
def _load_encoding():
    if not TIKTOKEN_AVAILABLE:
        return None
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None
