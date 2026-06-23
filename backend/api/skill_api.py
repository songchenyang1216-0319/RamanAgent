"""Skill 管理别名接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context, require_admin
from backend.services.skill_service import SkillManagementService


router = APIRouter(prefix="/api/skills", tags=["skills"])
skill_service = SkillManagementService()


class ToggleEnabledRequest(BaseModel):
    enabled: bool


@router.get("")
def get_skills() -> dict:
    return skill_service.list_skills(include_actions=True)


@router.get("/logs")
def get_skill_logs(current_user: dict = Depends(get_request_user_context), limit: int = 50) -> dict:
    return skill_service.list_logs(user_id=None if current_user["is_admin"] else current_user["user_id"], limit=limit)


@router.post("/upload")
async def upload_skill_zip(file: UploadFile = File(...), _: dict = Depends(require_admin)) -> dict:
    try:
        content = await file.read()
        return skill_service.upload_skill(filename=file.filename or "", content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skill 上传失败：{exc}") from exc


@router.delete("/{skill_name}")
def delete_skill(skill_name: str, _: dict = Depends(require_admin)) -> dict:
    try:
        return skill_service.delete_skill(skill_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{skill_name}/enabled")
def patch_skill_enabled(skill_name: str, payload: ToggleEnabledRequest, _: dict = Depends(require_admin)) -> dict:
    try:
        return skill_service.set_skill_enabled(skill_name, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": f"未找到 Skill: {skill_name}", "error_code": "SKILL_NOT_FOUND", "error_message": f"未找到 Skill: {skill_name}", "suggestion": "请刷新 Skill 列表后重试。"})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{skill_name}/actions/{action_name}/enabled")
def patch_action_enabled(skill_name: str, action_name: str, payload: ToggleEnabledRequest, _: dict = Depends(require_admin)) -> dict:
    try:
        return skill_service.set_action_enabled(skill_name, action_name, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": f"未找到子能力: {skill_name}/{action_name}", "error_code": "SKILL_ACTION_NOT_FOUND", "error_message": f"未找到子能力: {skill_name}/{action_name}", "suggestion": "请刷新 Skill 列表后重试。"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
