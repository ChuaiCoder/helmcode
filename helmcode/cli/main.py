from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from helmcode import __version__
from helmcode.cli.commands import apply, chat, config, diff, doctor, models, plan, run

console = Console()
app = typer.Typer(
    name="helmcode",
    help="CLI-first local codebase agent for planning, patching, and verification.",
    no_args_is_help=False,
)

app.add_typer(models.app, name="models")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    if version:
        console.print(f"helmcode {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        chat.start_interactive(Path.cwd())


app.command("run")(run.run_task)
app.command("plan")(plan.plan_task)
app.command("apply")(apply.apply_last_patch)
app.command("diff")(diff.show_pending_diff)
app.command("doctor")(doctor.doctor)
app.command("config")(config.config_cmd)


if __name__ == "__main__":
    app()
