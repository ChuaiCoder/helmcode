from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helmcode.memory.skill_store import Skill, SkillStore

console = Console()
app = typer.Typer(help="Manage project skills that are injected into task context.")


@app.command("list")
def list_skills(
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List built-in and project skills."""
    skills = SkillStore(workspace).list()
    if output_json:
        _print_json([skill.to_dict() for skill in skills])
        return
    _print_skill_table(skills)


@app.command("show")
def show_skill(
    skill_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show one skill."""
    skill = SkillStore(workspace).get(skill_id)
    if output_json:
        _print_json(skill.to_dict())
        return
    console.print(Panel(skill.instructions, title=f"{skill.id} ({skill.source})"))
    console.print(f"Description: {skill.description}")
    console.print(f"Triggers: {', '.join(skill.triggers)}")


@app.command("match")
def match_skills(
    task: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show skills that match a task."""
    skills = SkillStore(workspace).matching(task)
    if output_json:
        _print_json([skill.to_dict() for skill in skills])
        return
    _print_skill_table(skills)


@app.command("add")
def add_skill(
    skill_id: str = typer.Argument(...),
    description: str = typer.Option("", "--description", "-d"),
    trigger: list[str] = typer.Option(..., "--trigger", "-t", help="Trigger text. Repeatable."),
    instructions: str | None = typer.Option(None, "--instructions", "-i"),
    instructions_file: Path | None = typer.Option(None, "--instructions-file"),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing project skill."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Add a project skill."""
    instruction_text = _instruction_text(instructions, instructions_file)
    skill = SkillStore(workspace).add(
        skill_id=skill_id,
        description=description,
        triggers=trigger,
        instructions=instruction_text,
        overwrite=force,
    )
    if output_json:
        _print_json(skill.to_dict())
        return
    console.print(f"Added skill: {skill.id}")


@app.command("delete")
def delete_skill(
    skill_id: str = typer.Argument(...),
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Delete a project skill."""
    if not yes and not typer.confirm(f"Delete project skill {skill_id}?"):
        console.print("Delete cancelled.")
        return
    deleted = SkillStore(workspace).delete(skill_id)
    payload = {"skill_id": skill_id, "deleted": deleted}
    if output_json:
        _print_json(payload)
        return
    console.print("Deleted." if deleted else "Skill not found.")


def _instruction_text(instructions: str | None, instructions_file: Path | None) -> str:
    if instructions_file is not None:
        return instructions_file.read_text(encoding="utf-8")
    if instructions is not None:
        return instructions
    raise typer.BadParameter("provide --instructions or --instructions-file")


def _print_skill_table(skills: list[Skill]) -> None:
    table = Table(title="Skills")
    table.add_column("ID")
    table.add_column("Source")
    table.add_column("Triggers")
    table.add_column("Description")
    for skill in skills:
        table.add_row(skill.id, skill.source, ", ".join(skill.triggers), skill.description)
    console.print(table)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2, default=str))
