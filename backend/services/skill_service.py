from __future__ import annotations

import re
from typing import Any

from backend.services.task_trace_manager import TaskTraceManager
from backend.services.workspace_manager import WorkspaceManager
from backend.skills.registry import get_action, get_skill, list_skills, set_action_enabled, set_skill_enabled
from backend.skills.upload_service import delete_uploaded_skill, list_uploaded_skills, save_uploaded_skill


class SkillManagementService:
    def __init__(
        self,
        *,
        workspace_manager: WorkspaceManager | None = None,
        task_trace_manager: TaskTraceManager | None = None,
    ) -> None:
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.task_trace_manager = task_trace_manager or TaskTraceManager(workspace_manager=self.workspace_manager)

    def list_skills(self, *, include_actions: bool = True) -> dict[str, Any]:
        return list_skills(include_actions=include_actions)

    def list_logs(self, *, user_id: str | None = None, conversation_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        logs = self.task_trace_manager.list_skill_logs(user_id=user_id, conversation_id=conversation_id, limit=limit)
        return {"success": True, "logs": logs, "total": len(logs)}

    def upload_skill(self, *, filename: str, content: bytes) -> dict[str, Any]:
        if not str(filename or "").lower().endswith(".zip"):
            raise ValueError("仅支持上传 .zip 格式的 Skill 压缩包。")
        if not content:
            raise ValueError("上传文件为空。")
        return save_uploaded_skill(filename, content)

    def delete_skill(self, skill_name: str) -> dict[str, Any]:
        uploaded_items = list_uploaded_skills()
        normalized_target = self._normalize_skill_key(skill_name)
        has_uploaded_record = any(
            str(item.get("source") or "") == "uploaded"
            and normalized_target
            and normalized_target
            in {
                self._normalize_skill_key(item.get("name")),
                self._normalize_skill_key(item.get("skill_name")),
                self._normalize_skill_key(item.get("display_name")),
            }
            for item in uploaded_items
        )
        matched_skill = get_skill(skill_name)
        if matched_skill is not None and str(getattr(matched_skill, "source", "")) != "uploaded" and not has_uploaded_record:
            raise ValueError("仅支持删除已上传的 Skill，内置 Skill 不能删除。")
        return delete_uploaded_skill(skill_name)

    def set_skill_enabled(self, skill_name: str, enabled: bool) -> dict[str, Any]:
        if get_skill(skill_name) is None:
            raise KeyError(f"未找到 Skill: {skill_name}")
        return set_skill_enabled(skill_name, enabled)

    def set_action_enabled(self, skill_name: str, action_name: str, enabled: bool) -> dict[str, Any]:
        if get_skill(skill_name) is None:
            raise KeyError(f"未找到 Skill: {skill_name}")
        if get_action(skill_name, action_name) is None:
            raise KeyError(f"未找到子能力: {skill_name}/{action_name}")
        return set_action_enabled(skill_name, action_name, enabled)

    @staticmethod
    def _normalize_skill_key(value: object) -> str:
        return re.sub(r"\s+", "", str(value or "")).strip().lower()
