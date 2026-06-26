from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SKILL_DIR = ".agents/skills"


@dataclass(slots=True)
class Skill:
    id: str
    description: str
    triggers: list[str]
    instructions: str
    source: str = "project"

    def matches(self, task: str) -> bool:
        lowered = task.lower()
        return any(trigger.lower() in lowered for trigger in self.triggers)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "description": self.description,
            "triggers": self.triggers,
            "instructions": self.instructions,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, source: str = "project") -> "Skill":
        return cls(
            id=str(payload["id"]),
            description=str(payload.get("description", "")),
            triggers=[str(item) for item in payload.get("triggers", []) if isinstance(item, str)],
            instructions=str(payload.get("instructions", "")),
            source=source,
        )


class SkillStore:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path.resolve()
        self.skill_dir = self.workspace_path / SKILL_DIR

    def list(self) -> list[Skill]:
        skills = [*BUILTIN_SKILLS]
        if self.skill_dir.exists():
            for path in sorted(self.skill_dir.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        skills.append(Skill.from_dict(payload, source="project"))
                except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
        return sorted(skills, key=lambda item: (item.source != "builtin", item.id))

    def get(self, skill_id: str) -> Skill:
        for skill in self.list():
            if skill.id == skill_id:
                return skill
        raise KeyError(skill_id)

    def matching(self, task: str) -> list[Skill]:
        return [skill for skill in self.list() if skill.matches(task)]

    def add(
        self,
        *,
        skill_id: str,
        description: str,
        triggers: list[str],
        instructions: str,
        overwrite: bool = False,
    ) -> Skill:
        normalized_id = _normalize_skill_id(skill_id)
        if not triggers:
            raise ValueError("skill requires at least one trigger")
        if not instructions.strip():
            raise ValueError("skill requires instructions")
        skill = Skill(
            id=normalized_id,
            description=description,
            triggers=triggers,
            instructions=instructions,
            source="project",
        )
        self.skill_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(normalized_id)
        if path.exists() and not overwrite:
            raise FileExistsError(path)
        path.write_text(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return skill

    def delete(self, skill_id: str) -> bool:
        path = self._path_for(_normalize_skill_id(skill_id))
        if not path.exists():
            return False
        path.unlink()
        return True

    def _path_for(self, skill_id: str) -> Path:
        return self.skill_dir / f"{skill_id}.json"


BUILTIN_SKILLS = [
    Skill(
        id="codingplan-routing",
        description="Route Coding Plan work across cheap and expensive models.",
        triggers=["codingplan", "coding plan", "quota", "multi-agent", "multiagent", "额度"],
        instructions=(
            "For Coding Plan tasks, separate cheap discovery and summarization from expensive "
            "planning, coding, review, and repair calls. Prefer `helmcode agents plan` before "
            "provider calls when the user is comparing model quota usage."
        ),
        source="builtin",
    )
]


def render_skills_for_context(skills: list[Skill]) -> str:
    if not skills:
        return ""
    rendered: list[str] = []
    for skill in skills:
        rendered.append(
            f"### {skill.id}\n"
            f"Source: {skill.source}\n"
            f"Description: {skill.description}\n"
            f"Instructions:\n{skill.instructions}"
        )
    return "\n\n".join(rendered)


def _normalize_skill_id(skill_id: str) -> str:
    normalized = skill_id.strip().lower().replace("_", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", normalized):
        raise ValueError("skill id must match [a-z0-9][a-z0-9-]{0,63}")
    return normalized
