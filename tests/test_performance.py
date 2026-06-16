from __future__ import annotations

import time
from pathlib import Path

import pytest

from helmcode.context.token_budget import TokenBudget, TIKTOKEN_AVAILABLE
from helmcode.context.file_index import FileIndex


class TestTokenBudgetPerformance:
    def test_tiktoken_is_available(self) -> None:
        assert TIKTOKEN_AVAILABLE, "tiktoken should be installed"

    def test_token_counting_accuracy(self) -> None:
        budget = TokenBudget()
        text = "Hello world, this is a test of token counting."
        token_count = budget._count_tokens(text)
        char_count = len(text)
        assert token_count > 0
        assert token_count < char_count

    def test_token_truncation(self) -> None:
        budget = TokenBudget(max_tokens=10)
        long_text = "This is a long text that should be truncated when exceeding the token limit. " * 10
        sections = [long_text]
        result = budget.fit(sections)
        assert "[truncated]" in result
        assert len(result) < len(long_text)

    def test_token_budget_performance(self) -> None:
        budget = TokenBudget(max_tokens=1000)
        sections = [
            "Section 1: " + "word " * 100,
            "Section 2: " + "word " * 200,
            "Section 3: " + "word " * 300,
        ]
        start = time.time()
        result = budget.fit(sections)
        end = time.time()
        assert end - start < 1.0
        assert "Section 1" in result
        assert "Section 2" in result


class TestFileIndexPerformance:
    def test_file_index_caching(self, tmp_path: Path) -> None:
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        index = FileIndex(tmp_path)
        files1 = index.list_files(use_cache=False)
        files2 = index.list_files(use_cache=True)
        assert files1 == files2

    def test_incremental_update(self, tmp_path: Path) -> None:
        (tmp_path / "file1.txt").write_text("content1")
        index = FileIndex(tmp_path)
        index.update_cache()
        (tmp_path / "file2.txt").write_text("content2")
        changed = index.get_changed_files()
        assert "file2.txt" in changed

    def test_incremental_update_returns_empty_when_cache_is_current(self, tmp_path: Path) -> None:
        (tmp_path / "file1.txt").write_text("content1")
        index = FileIndex(tmp_path)

        first_changed = index.update_cache()
        second_changed = index.update_cache()

        assert first_changed == ["file1.txt"]
        assert second_changed == []

    def test_incremental_update_detects_modified_and_deleted_files(self, tmp_path: Path) -> None:
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")
        index = FileIndex(tmp_path)
        index.update_cache()

        file1.write_text("changed")
        file2.unlink()
        changed = sorted(index.get_changed_files())

        assert changed == ["file1.txt", "file2.txt"]

    def test_file_hash_computation(self, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("test content")
        index = FileIndex(tmp_path)
        hash1 = index._compute_file_hash(tmp_path / "test.txt")
        hash2 = index._compute_file_hash(tmp_path / "test.txt")
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_file_index_performance(self, tmp_path: Path) -> None:
        for i in range(100):
            (tmp_path / f"file_{i}.txt").write_text(f"content {i}")
        index = FileIndex(tmp_path)
        start = time.time()
        files = index.list_files(limit=50)
        end = time.time()
        assert end - start < 1.0
        assert len(files) == 50


class TestAsyncProviderPerformance:
    def test_async_method_exists(self) -> None:
        from helmcode.models.provider import ProviderAdapter

        assert hasattr(ProviderAdapter, "chat_async")
        assert hasattr(ProviderAdapter, "list_models_async")

    def test_openai_compatible_has_async(self) -> None:
        from helmcode.models.openai_compatible import OpenAICompatibleProvider

        assert hasattr(OpenAICompatibleProvider, "chat_async")
        assert hasattr(OpenAICompatibleProvider, "list_models_async")
