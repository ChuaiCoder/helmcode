from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from helmcode import __version__
from helmcode.cli.commands import (
    agents,
    allocations,
    apply,
    checkpoints,
    chat,
    compact,
    config,
    context,
    cost,
    diff,
    doctor,
    index,
    init_project,
    mcp,
    models,
    plan,
    quota,
    routes,
    run,
    savings,
    sessions,
    setup,
    skills,
    tokens,
    tools,
)

console = Console()
app = typer.Typer(
    name="helmcode",
    help="CLI-first local codebase agent for planning, patching, and verification.",
    no_args_is_help=False,
)

app.add_typer(models.app, name="models")
app.add_typer(agents.app, name="agents")
app.add_typer(sessions.app, name="sessions")
app.add_typer(checkpoints.app, name="checkpoint")
app.add_typer(index.app, name="index")
app.add_typer(skills.app, name="skills")
app.add_typer(tools.app, name="tools")
app.add_typer(mcp.app, name="mcp")
app.add_typer(quota.app, name="quota")


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
app.command("chat")(chat.chat_cmd)
app.command("code")(chat.chat_cmd)
app.command("compact")(compact.compact_cmd)
app.command("context")(context.context_cmd)
app.command("cost")(cost.cost_cmd)
app.command("routes")(routes.routes_cmd)
app.command("savings")(savings.savings_cmd)
app.command("allocations")(allocations.allocations_cmd)
app.command("plans")(allocations.allocations_cmd)
app.command("apply")(apply.apply_last_patch)
app.command("diff")(diff.show_pending_diff)
app.command("doctor")(doctor.doctor)
app.command("config")(config.config_cmd)
app.command("events")(sessions.events_command)
app.command("stats")(sessions.stats_command)
app.command("tokens")(tokens.tokens_cmd)
app.command("replay")(sessions.replay_command)
app.command("prune-sessions")(sessions.prune_command)
app.command("setup")(setup.setup_cmd)
app.command("init")(init_project.init_cmd)
app.command("restore")(checkpoints.restore_checkpoint)


if __name__ == "__main__":
    app()
