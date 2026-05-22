"""模型注册表 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.model_registry_service import ModelRegistryService


router = APIRouter(prefix="/api/models", tags=["models"])
service = ModelRegistryService()


class SetCurrentModelRequest(BaseModel):
    model_version: str


@router.get("/current")
def get_current_model() -> dict:
    result = service.get_default_model()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error_message"])
    return result


@router.get("")
def list_models() -> dict:
    result = service.list_models()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error_message"])
    return result


@router.get("/{model_version}")
def get_model_version(model_version: str) -> dict:
    result = service.get_model_version(model_version)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["error_message"])
    return result


@router.get("/{model_version}/check")
def check_model(model_version: str) -> dict:
    result = service.check_model_artifacts(model_version)
    if not result["success"] and result["data"] is None:
        raise HTTPException(status_code=404, detail=result["error_message"])
    return result


@router.post("/current")
def set_current_model(request: SetCurrentModelRequest) -> dict:
    result = service.set_default_model(request.model_version)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error_message"])
    return result
