"""Long-term user memory stored outside conversation workspaces."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.services.workspace_manager import now_iso, read_json, safe_segment, write_json, DEFAULT_USER_ID
from raman_core.methanol.config import PROJECT_ROOT


USER_STORAGE_ROOT = PROJECT_ROOT / "storage" / "users"


class UserMemoryManager:
    """Manage durable user-level preferences and recent behavior."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else USER_STORAGE_ROOT

    def _user_id(self, user_id: str | None) -> str:
        return safe_segment(user_id, fallback=DEFAULT_USER_ID)

    def _path(self, user_id: str | None) -> Path:
        return self.root / self._user_id(user_id) / "memory.json"

    def _default_memory(self, user_id: str | None) -> dict[str, Any]:
        return {
            "user_id": self._user_id(user_id),
            "preferred_provider": None,
            "preferred_model": None,
            "recent_skills": [],
            "profile": {},
            "updated_at": now_iso(),
        }

    def get_user_memory(self, user_id: str | None) -> dict[str, Any]:
        path = self._path(user_id)
        memory = read_json(path, self._default_memory(user_id))
        if not isinstance(memory, dict):
            memory = self._default_memory(user_id)
        memory.setdefault("user_id", self._user_id(user_id))
        memory.setdefault("preferred_provider", None)
        memory.setdefault("preferred_model", None)
        memory.setdefault("recent_skills", [])
        memory.setdefault("profile", {})
        return memory

    def update_user_memory(self, user_id: str | None, patch: dict[str, Any]) -> dict[str, Any]:
        memory = self.get_user_memory(user_id)
        merged = self._deep_merge(memory, dict(patch or {}))
        merged["user_id"] = self._user_id(user_id)
        merged["updated_at"] = now_iso()
        write_json(self._path(user_id), merged)
        return merged

    def get_preferred_model(self, user_id: str | None) -> str | None:
        value = self.get_user_memory(user_id).get("preferred_model")
        return str(value) if value else None

    def get_preferred_provider(self, user_id: str | None) -> str | None:
        value = self.get_user_memory(user_id).get("preferred_provider")
        return str(value) if value else None

    def set_preferred_model(self, user_id: str | None, model_id: str, provider_id: str | None = None) -> dict[str, Any]:
        patch = {"preferred_model": str(model_id or "").strip() or None}
        if provider_id is not None:
            patch["preferred_provider"] = str(provider_id or "").strip() or None
        return self.update_user_memory(user_id, patch)

    def get_recent_skills(self, user_id: str | None) -> list[str]:
        value = self.get_user_memory(user_id).get("recent_skills") or []
        return [str(item) for item in value if item]

    def add_recent_skill(self, user_id: str | None, skill_name: str) -> dict[str, Any]:
        skill = str(skill_name or "").strip()
        skills = [item for item in self.get_recent_skills(user_id) if item != skill]
        if skill:
            skills.insert(0, skill)
        return self.update_user_memory(user_id, {"recent_skills": skills[:20]})

    def _deep_merge(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
