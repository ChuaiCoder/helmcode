from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from helmcode.agent.loop import AgentLoop
from helmcode.agent.state import AgentState
from helmcode.context.workspace import Workspace
from helmcode.core.config import load_config
from helmcode.core.constants import MODEL_ROLE_PLANNING
from helmcode.models.model_registry import ModelRegistry
from helmcode.models.selector import ModelSelector

console = Console()


def plan_task(task: str = typer.Argument(...), workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
    """Generate a plan without modifying files."""
    config = load_config()
    ws = Workspace.discover(workspace)
    selector = ModelSelector(config.model_roles)
    model_id = selector.select(MODEL_ROLE_PLANNING)
    registry = ModelRegistry.from_config(config)
    provider = registry.provider_for_model(model_id)
    state = AgentState.start(ws.root_path, task)
    agent = AgentLoop(ws, provider, model_id, state, permission_mode=config.permission_mode)
    result = agent.plan(task)
    console.print(Panel(result.content, title="Plan"))
