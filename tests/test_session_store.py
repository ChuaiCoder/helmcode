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
    store.record("session-a", "model_called", {"model_id": "main:planner"})
    store.record("session-a", "patch_created", {"files": ["a.py"]})
    store.record("session-a", "patch_applied", {"files": ["a.py"]})
    store.record("session-b", "command_result", {"ok": True})

    recent = store.list_recent_events(limit=2)
    stats = store.stats()

    assert [event.event_type for event in recent] == ["command_result", "patch_applied"]
    assert stats.session_count == 2
    assert stats.event_count == 5
    assert stats.model_call_count == 1
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
