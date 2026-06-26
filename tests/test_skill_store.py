from __future__ import annotations

from pathlib import Path

from helmcode.memory.skill_store import SkillStore, render_skills_for_context


def test_skill_store_lists_builtin_and_matches_codingplan(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)

    skills = store.list()
    matched = store.matching("optimize codingplan quota routing")

    assert [skill.id for skill in skills] == ["codingplan-routing"]
    assert [skill.id for skill in matched] == ["codingplan-routing"]


def test_skill_store_adds_matches_and_deletes_project_skill(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)
    skill = store.add(
        skill_id="Api_Review",
        description="API review guidance",
        triggers=["api"],
        instructions="Check API compatibility and tests.",
    )

    assert skill.id == "api-review"
    assert (tmp_path / ".agents" / "skills" / "api-review.json").exists()
    assert [item.id for item in store.matching("change api response")] == ["api-review"]
    assert store.delete("api-review") is True
    assert [item.id for item in store.matching("change api response")] == []


def test_render_skills_for_context_includes_instructions(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)
    skill = store.add(
        skill_id="security",
        description="security checks",
        triggers=["auth"],
        instructions="Check auth boundary conditions.",
    )

    rendered = render_skills_for_context([skill])

    assert "### security" in rendered
    assert "Check auth boundary conditions." in rendered
