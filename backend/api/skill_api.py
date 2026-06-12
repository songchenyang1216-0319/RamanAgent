"""Skill 管理别名接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context, require_admin
from backend.services.task_trace_manager import TaskTraceManager
from backend.services.workspace_manager import WorkspaceManager
from backend.skills.registry import get_action, get_skill, list_skills, set_action_enabled, set_skill_enabled


router = APIRouter(prefix="/api/skills", tags=["skills"])
workspace_manager = WorkspaceManager()
task_trace_manager = TaskTraceManager(workspace_manager=workspace_manager)


class ToggleEnabledRequest(BaseModel):
    enabled: bool


@router.get("")
def get_skills() -> dict:
    return list_skills(include_actions=True)


@router.get("/logs")
def get_skill_logs(current_user: dict = Depends(get_request_user_context), limit: int = 50) -> dict:
    logs = task_trace_manager.list_skill_logs(None if current_user["is_admin"] else current_user["user_id"], limit=limit)
    return {"success": True, "logs": logs, "total": len(logs)}


@router.patch("/{skill_name}/enabled")
def patch_skill_enabled(skill_name: str, payload: ToggleEnabledRequest, _: dict = Depends(require_admin)) -> dict:
    if get_skill(skill_name) is None:
        raise HTTPException(status_code=404, detail={"message": f"未找到 Skill: {skill_name}", "error_code": "SKILL_NOT_FOUND", "error_message": f"未找到 Skill: {skill_name}", "suggestion": "请刷新 Skill 列表后重试。"})
    return set_skill_enabled(skill_name, payload.enabled)


@router.patch("/{skill_name}/actions/{action_name}/enabled")
def patch_action_enabled(skill_name: str, action_name: str, payload: ToggleEnabledRequest, _: dict = Depends(require_admin)) -> dict:
    if get_skill(skill_name) is None or get_action(skill_name, action_name) is None:
        raise HTTPException(status_code=404, detail={"message": f"未找到子能力: {skill_name}/{action_name}", "error_code": "SKILL_ACTION_NOT_FOUND", "error_message": f"未找到子能力: {skill_name}/{action_name}", "suggestion": "请刷新 Skill 列表后重试。"})
    return set_action_enabled(skill_name, action_name, payload.enabled)
