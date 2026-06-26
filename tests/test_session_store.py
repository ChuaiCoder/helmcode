from __future__ import annotations

from pathlib import Path

from helmcode.memory.session_store import SessionStore


def test_session_store_lists_sessions_with_task_and_counts(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})
    store.record("session-a", "model_called", {"model_id": "main:coder"})
    store.record("session-b", "user_message", {"content": "review patch"})

    sessions = store.list_sessions(limit=10)

    assert [session.session_id for session in sessions] == ["session-b", "session-a"]
    assert sessions[0].task == "review patch"
    assert sessions[0].event_count == 1
    assert sessions[1].task == "add tests"
    assert sessions[1].event_count == 2


def test_session_store_lists_recent_events_and_stats(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "add tests"})
    store.record(
        "session-a",
        "model_called",
        {
            "model_id": "main:planner",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 30,
                "total_tokens": 130,
                "cached_tokens": 70,
                "cache_miss_tokens": 30,
            },
        },
    )
    store.record(
        "session-a",
        "task_allocated",
        {
            "baseline_cost_score": 8,
            "selected_cost_score": 6,
            "estimated_savings_score": 2,
        },
    )
    store.record("session-a", "patch_created", {"files": ["a.py"]})
    store.record("session-a", "patch_applied", {"files": ["a.py"]})
    store.record(
        "session-b",
        "task_allocated",
        {
            "baseline_cost_score": 16,
            "selected_cost_score": 9,
            "estimated_savings_score": 7,
        },
    )
    store.record("session-b", "task_budget_blocked", {"selected_cost_score": 9, "max_cost_score": 4})
    store.record("session-b", "command_result", {"ok": True})

    recent = store.list_recent_events(limit=2)
    allocations = store.list_events_by_type("task_allocated")
    latest_allocation = store.list_events_by_type("task_allocated", limit=1)
    session_allocations = store.list_events_by_type("task_allocated", session_id="session-a")
    stats = store.stats()

    assert [event.event_type for event in recent] == ["command_result", "task_budget_blocked"]
    assert [event.session_id for event in allocations] == ["session-b", "session-a"]
    assert [event.session_id for event in latest_allocation] == ["session-b"]
    assert [event.session_id for event in session_allocations] == ["session-a"]
    assert stats.session_count == 2
    assert stats.event_count == 8
    assert stats.model_call_count == 1
    assert stats.model_prompt_tokens == 100
    assert stats.model_completion_tokens == 30
    assert stats.model_total_tokens == 130
    assert stats.model_cached_tokens == 70
    assert stats.model_cache_miss_tokens == 30
    assert stats.coding_plan_allocation_count == 2
    assert stats.coding_plan_baseline_cost_score == 24
    assert stats.coding_plan_selected_cost_score == 15
    assert stats.coding_plan_estimated_savings_score == 9
    assert stats.coding_plan_budget_blocked_count == 1
    assert stats.patch_created_count == 1
    assert stats.patch_applied_count == 1
    assert stats.command_result_count == 1
    assert stats.event_counts["user_message"] == 1


def test_session_store_deletes_and_prunes_sessions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, enable_structured_logging=False)
    store.record("session-a", "user_message", {"content": "first"})
    store.record("session-b", "user_message", {"content": "second"})
    store.record("session-c", "user_message", {"content": "third"})

    pruned = store.prune_sessions(keep=1)

    assert [session.session_id for session in pruned] == ["session-b", "session-a"]
    assert [session.session_id for session in store.list_sessions(limit=10)] == ["session-c"]
    assert store.delete_session("session-c") == 1
    assert store.list_sessions(limit=10) == []
