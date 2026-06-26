from __future__ import annotations

from pathlib import Path

from helmcode.cli.commands import retry
from helmcode.memory.session_store import SessionStore


def test_resolve_retry_task_uses_latest_user_message(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record("session-a", "user_message", {"content": "first task"})
    store.record("session-b", "user_message", {"content": "second task"})

    task = retry.resolve_retry_task(tmp_path)

    assert task.session_id == "session-b"
    assert task.task == "second task"


def test_resolve_retry_task_can_target_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record("session-a", "user_message", {"content": "first task"})
    store.record("session-b", "user_message", {"content": "second task"})

    task = retry.resolve_retry_task(tmp_path, "session-a")

    assert task.session_id == "session-a"
    assert task.task == "first task"


def test_execute_retry_task_recommend_uses_recommend_route(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def record_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(retry.run_command, "run_task", record_run)

    retry.execute_retry_task(
        "add tests",
        workspace=tmp_path,
        mode="recommend",
        routing="quota",
        model="main:coder",
        max_cost_score=5,
        session_budget_score=10,
        budget_key="chat",
        yes=True,
        no_tests=True,
        no_preplan_cache=True,
    )

    assert calls == [
        {
            "task": "add tests",
            "workspace": tmp_path,
            "yes": True,
            "no_tests": True,
            "routing": "recommend",
            "model": "main:coder",
            "max_cost_score": 5,
            "no_preplan_cache": True,
        }
    ]


def test_execute_retry_task_plan_uses_plan_command(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def record_plan(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(retry.plan_command, "plan_task", record_plan)

    retry.execute_retry_task(
        "design feature",
        workspace=tmp_path,
        mode="plan",
        routing="fixed",
        model=None,
        max_cost_score=None,
        session_budget_score=10,
        budget_key="chat",
        yes=False,
        no_tests=False,
        no_preplan_cache=False,
    )

    assert calls == [
        {
            "task": "design feature",
            "workspace": tmp_path,
            "routing": "fixed",
            "model": None,
            "max_cost_score": None,
            "session_budget_score": 10,
            "budget_key": "chat",
            "no_preplan_cache": False,
        }
    ]
