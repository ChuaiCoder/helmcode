from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from helmcode.agent.allocation import CodingPlanTaskAllocator
from helmcode.agent.runtime import AgentRuntime
from helmcode.agent.session import AgentSession
from helmcode.cli.main import app
from helmcode.context.workspace import Workspace
from helmcode.core.config import HelmcodeConfig, ModelProfileConfig
from helmcode.core.exceptions import ModelError
from helmcode.memory.coding_plan_budget import CodingPlanBudgetLedger
from helmcode.models.quota import QuotaAwareSelector, QuotaLedger


class RecordingSessionStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def record(self, session_id: str, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((session_id, event_type, payload))


def _config() -> HelmcodeConfig:
    return HelmcodeConfig(
        model_roles={
            "default": "main:fast",
            "fast": "main:fast",
            "planning": "main:planner",
            "coding": "main:coder",
            "review": "main:review",
        },
        model_profiles=[
            ModelProfileConfig(
                id="main:fast",
                preferred_for=["repo_scan", "summarize", "classify"],
                cost_tier="low",
            ),
            ModelProfileConfig(
                id="main:planner",
                preferred_for=["plan"],
                cost_tier="medium",
            ),
            ModelProfileConfig(
                id="main:coder",
                preferred_for=["code_patch", "repair"],
                cost_tier="high",
            ),
            ModelProfileConfig(
                id="main:review",
                preferred_for=["review"],
                cost_tier="medium",
            ),
        ],
    )


def _allocation(tmp_path: Path):
    config = _config()
    allocator = CodingPlanTaskAllocator(
        config,
        QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl")),
    )
    return allocator.allocate("add a small helper")


def test_coding_plan_budget_ledger_records_selected_cost(tmp_path: Path) -> None:
    ledger = CodingPlanBudgetLedger.for_workspace(tmp_path)
    allocation = _allocation(tmp_path)

    status = ledger.record_allocation(allocation, key="chat")

    assert status.key == "chat"
    assert status.allocation_count == 1
    assert status.selected_cost_score == 6
    assert status.baseline_cost_score == 8
    assert status.estimated_savings_score == 2
    assert status.remaining(10) == 4
    decision = ledger.check(allocation, key="chat", max_score=10)
    assert decision.allowed is False
    assert decision.projected_selected_cost_score == 12


def test_runtime_blocks_before_provider_when_session_budget_exceeded(tmp_path: Path) -> None:
    config = _config()
    store = RecordingSessionStore()
    runtime = AgentRuntime(
        workspace=Workspace.discover(tmp_path),
        selector=QuotaAwareSelector(config, QuotaLedger(tmp_path / "quota.jsonl")),
        session_store=store,
    )
    session = AgentSession(
        session_id="session-1",
        workspace_path=tmp_path,
        user_task="add a small helper",
        created_at=datetime.now(UTC),
    )

    first = runtime.allocate_task(
        session=session,
        task="add a small helper",
        session_budget_score=10,
        budget_key="chat",
    )
    assert first is not None

    try:
        runtime.allocate_task(
            session=session,
            task="add a small helper",
            session_budget_score=10,
            budget_key="chat",
        )
    except ModelError as exc:
        assert "session budget exceeded" in str(exc)
    else:
        raise AssertionError("session budget should block the second allocation")

    event_types = [event_type for _, event_type, _ in store.events]
    assert "task_session_budget_reserved" in event_types
    assert "task_session_budget_blocked" in event_types
    status = CodingPlanBudgetLedger.for_workspace(tmp_path).status("chat")
    assert status.selected_cost_score == 6
    assert status.blocked_count == 1


def test_budget_cli_outputs_json_status(tmp_path: Path) -> None:
    ledger = CodingPlanBudgetLedger.for_workspace(tmp_path)
    ledger.record_allocation(_allocation(tmp_path), key="chat")

    result = CliRunner().invoke(
        app,
        ["budget", "--workspace", str(tmp_path), "--key", "chat", "--max-score", "10", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["key"] == "chat"
    assert payload[0]["selected_cost_score"] == 6
    assert payload[0]["remaining_score"] == 4


def test_budget_cli_resets_key(tmp_path: Path) -> None:
    ledger = CodingPlanBudgetLedger.for_workspace(tmp_path)
    ledger.record_allocation(_allocation(tmp_path), key="chat")

    result = CliRunner().invoke(
        app,
        ["budget", "--workspace", str(tmp_path), "--key", "chat", "--reset", "--yes", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["removed"] == 1
    assert ledger.status("chat").selected_cost_score == 0
