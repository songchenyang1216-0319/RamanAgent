from __future__ import annotations

from backend.skills.skill_registry import SkillRegistry


class SkillRouter:
    def __init__(self) -> None:
        self.registry = SkillRegistry()

    def resolve_skill_mode(self, skill_name: str) -> str:
        skill = self.registry.get(skill_name)
        if skill is None:
            return "invalid"
        if getattr(skill, "skill_mode", ""):
            return str(getattr(skill, "skill_mode"))
        has_actions = bool(getattr(skill, "actions", []))
        return "executable" if has_actions else "invalid"

    def match_uploaded_skill(self, message: str, file_suffix: str | None = None):
        return self.registry.match(message, file_suffix=file_suffix)

