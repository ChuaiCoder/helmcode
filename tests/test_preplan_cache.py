from __future__ import annotations

from helmcode.memory.preplan_cache import PreplanCache


def test_preplan_cache_keys_change_with_context(tmp_path) -> None:
    cache = PreplanCache(tmp_path)

    first = cache.key_for(
        agent_id="scout",
        task_type="repo_scan",
        model_id="main:fast",
        task="inspect auth",
        base_context="auth.py v1",
        previous_outputs=[],
    )
    second = cache.key_for(
        agent_id="scout",
        task_type="repo_scan",
        model_id="main:fast",
        task="inspect auth",
        base_context="auth.py v2",
        previous_outputs=[],
    )

    assert first != second


def test_preplan_cache_round_trips_entries(tmp_path) -> None:
    cache = PreplanCache(tmp_path)

    cache.put(
        key="abc",
        agent_id="scout",
        task_type="repo_scan",
        model_id="main:fast",
        content="check auth.py",
    )

    restored = PreplanCache(tmp_path).get("abc")
    assert restored is not None
    assert restored.agent_id == "scout"
    assert restored.content == "check auth.py"
