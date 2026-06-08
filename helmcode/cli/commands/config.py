from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax

from helmcode.core.config import load_config, save_user_config, user_config_path

console = Console()


def config_cmd(
    show: bool = typer.Option(True, "--show/--no-show", help="Show current config."),
    init: bool = typer.Option(False, "--init", help="Create a user config file from defaults."),
) -> None:
    """View or initialize configuration."""
    config = load_config()
    if init:
        path = save_user_config(config)
        console.print(f"Wrote user config: {path}")
    if show:
        import yaml

        text = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False)
        console.print(Syntax(text, "yaml"))
        console.print(f"User config path: {user_config_path()}")
