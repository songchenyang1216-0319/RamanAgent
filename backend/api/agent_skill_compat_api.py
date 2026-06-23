from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from backend.api.deprecation import apply_deprecation_headers
from backend.services.skill_service import SkillManagementService
from backend.services.workspace_manager import DEFAULT_USER_ID


router = APIRouter(prefix="/api/agent", tags=["Legacy Compatibility"])
skill_service = SkillManagementService()


class ToggleEnabledRequest(BaseModel):
    enabled: bool


@router.get("/skills")
def get_skills(response: Response) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/skills", successor_path="/api/skills")
    return skill_service.list_skills(include_actions=True)


@router.get("/skills/logs")
def get_skill_logs(
    response: Response,
    user_id: str = DEFAULT_USER_ID,
    conversation_id: str | None = None,
    limit: int = 50,
) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/skills/logs", successor_path="/api/skills/logs")
    from backend.agent import agent_router as legacy_agent_router

    logs = legacy_agent_router.task_trace_manager.list_skill_logs(user_id=user_id, conversation_id=conversation_id, limit=limit)
    return {"success": True, "logs": logs, "total": len(logs)}


@router.post("/skills/upload")
async def upload_skill_zip(response: Response, file: UploadFile = File(...)) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/skills/upload", successor_path="/api/skills/upload")
    try:
        content = await file.read()
        return skill_service.upload_skill(filename=file.filename or "", content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skill 上传失败：{exc}") from exc


@router.delete("/skills/{skill_name}")
def delete_skill(skill_name: str, response: Response) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/skills/{skill_name}", successor_path="/api/skills/{skill_name}")
    try:
        return skill_service.delete_skill(skill_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skill 删除失败：{exc}") from exc


@router.patch("/skills/{skill_name}/enabled")
def patch_skill_enabled(skill_name: str, payload: ToggleEnabledRequest, response: Response) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/skills/{skill_name}/enabled", successor_path="/api/skills/{skill_name}/enabled")
    try:
        return skill_service.set_skill_enabled(skill_name, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/skills/{skill_name}/actions/{action_name}/enabled")
def patch_action_enabled(skill_name: str, action_name: str, payload: ToggleEnabledRequest, response: Response) -> dict:
    apply_deprecation_headers(
        response,
        legacy_path="/api/agent/skills/{skill_name}/actions/{action_name}/enabled",
        successor_path="/api/skills/{skill_name}/actions/{action_name}/enabled",
    )
    try:
        return skill_service.set_action_enabled(skill_name, action_name, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
