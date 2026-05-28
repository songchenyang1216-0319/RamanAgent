from __future__ import annotations

from typing import Any

from backend.skills.registry import execute_skill, get_skill, list_skills, match_uploaded_skill


class SkillRegistry:
    def get(self, skill_name: str):
        return get_skill(skill_name)

    def list(self, include_actions: bool = True) -> dict[str, Any]:
        return list_skills(include_actions=include_actions)

    def execute(self, skill_name: str, action_name: str | None = None, **kwargs: Any):
        return execute_skill(skill_name, action_name=action_name, **kwargs)

    def match(self, message: str, file_suffix: str | None = None):
        return match_uploaded_skill(message, file_suffix=file_suffix)

