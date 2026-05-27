"""LLM 模型列表与切换 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.llm_registry_service import LLMRegistryService


router = APIRouter(prefix="/api/llm", tags=["llm"])
service = LLMRegistryService()


class SwitchLLMModelRequest(BaseModel):
    provider: str = Field(..., description="模型供应商标识")
    model: str = Field(..., description="模型 ID")


@router.get("/models")
def list_models() -> dict:
    result = service.list_models()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error_message") or "读取 LLM 模型列表失败")
    return result


@router.get("/models/current")
def get_current_model() -> dict:
    result = service.get_current_model()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error_message") or "读取当前 LLM 模型失败")
    return result


@router.post("/models/current")
def switch_current_model(payload: SwitchLLMModelRequest) -> dict:
    result = service.switch_current_model(payload.provider, payload.model)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error_message") or "切换 LLM 模型失败")
    return {
        "success": True,
        "current": result["current"],
    }

