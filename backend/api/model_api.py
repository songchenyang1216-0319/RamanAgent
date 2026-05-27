"""Provider-first LLM model management APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.core.model_registry import ModelRegistry
from backend.core.model_router import ModelRouter
from backend.services.workspace_manager import DEFAULT_USER_ID


router = APIRouter(prefix="/api/models", tags=["llm-models"])
registry = ModelRegistry()
model_router = ModelRouter(registry=registry)


class ModelSelectRequest(BaseModel):
    provider_id: str
    model_id: str
    conversation_id: str | None = None
    user_id: str = DEFAULT_USER_ID


@router.get("/providers")
def list_providers() -> list[dict]:
    registry.reload()
    return registry.list_providers()


@router.get("/providers/{provider_id}/models")
def list_provider_models(
    provider_id: str,
    conversation_id: str | None = Query(default=None),
    user_id: str = Query(default=DEFAULT_USER_ID),
) -> list[dict]:
    registry.reload()
    ok, message = registry.validate_provider(provider_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error_code": "PROVIDER_NOT_FOUND",
                "message": "平台不存在，请重新选择。",
                "error_message": message,
                "suggestion": "请刷新模型列表后重新选择平台。",
            },
        )
    current = model_router.get_selected_model(user_id=user_id, conversation_id=conversation_id)
    items = []
    for model in registry.list_models(provider_id):
        items.append(
            {
                "id": model["id"],
                "display_name": model["display_name"],
                "model_type": model.get("model_type") or "unknown",
                "supports_vision": bool(model.get("supports_vision")),
                "supported_categories": list(model.get("supported_categories") or []),
                "supported_category_labels": list(model.get("supported_category_labels") or []),
                "category_summary": model.get("category_summary") or "",
                "category_source": model.get("category_source") or "",
                "category_reason": model.get("category_reason") or "",
                "category_status": model.get("category_status") or "",
                "selected": current["provider_id"] == provider_id and current["model_id"] == model["id"],
            }
        )
    return items


@router.get("/current")
def get_current_model(
    conversation_id: str | None = Query(default=None),
    user_id: str = Query(default=DEFAULT_USER_ID),
) -> dict:
    try:
        current = model_router.get_selected_model(user_id=user_id, conversation_id=conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error_code": "MODEL_CURRENT_FAILED",
                "message": "读取当前大模型失败",
                "error_message": str(exc),
                "suggestion": "请检查 .env 中的 LLM_PROVIDER / LLM_MODEL 与平台模型列表。",
            },
        ) from exc
    return {
        "provider_id": current["provider_id"],
        "provider_name": current["provider_name"],
        "model_id": current["model_id"],
        "model_name": current["model_name"],
        "model_type": current.get("model_type") or "unknown",
        "supports_vision": bool(current.get("supports_vision")),
        "supported_categories": list(current.get("supported_categories") or []),
        "supported_category_labels": list(current.get("supported_category_labels") or []),
        "category_summary": current.get("category_summary") or "",
        "category_source": current.get("category_source") or "",
        "category_reason": current.get("category_reason") or "",
        "category_status": current.get("category_status") or "",
        "configured": current["configured"],
        "reason": current.get("reason") or "",
    }


@router.post("/select")
def select_model(payload: ModelSelectRequest) -> dict:
    try:
        current = model_router.set_selected_model(
            payload.provider_id,
            payload.model_id,
            user_id=payload.user_id,
            conversation_id=payload.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error_code": "MODEL_SELECT_FAILED",
                "message": "切换模型失败",
                "error_message": str(exc),
                "suggestion": "请确认平台已配置 API Key、BASE_URL，并且模型属于该平台。",
            },
        ) from exc
    return {
        "success": True,
        "provider_id": current["provider_id"],
        "provider_name": current["provider_name"],
        "model_id": current["model_id"],
        "model_name": current["model_name"],
        "model_type": current.get("model_type") or "unknown",
        "supports_vision": bool(current.get("supports_vision")),
        "supported_categories": list(current.get("supported_categories") or []),
        "supported_category_labels": list(current.get("supported_category_labels") or []),
        "category_summary": current.get("category_summary") or "",
        "category_source": current.get("category_source") or "",
        "category_reason": current.get("category_reason") or "",
        "category_status": current.get("category_status") or "",
        "message": f"已切换到{current['provider_name']} / {current['model_id']}",
    }


@router.post("/refresh")
def refresh_models() -> dict:
    try:
        registry.reload()
        settings = registry.get_refresh_settings()
        return {
            "success": True,
            "message": "模型配置已从 .env 重新加载。",
            "refresh_enabled": settings["enabled"],
            "providers": registry.list_providers(),
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"刷新失败，但系统仍可继续使用：{exc}",
            "providers": registry.list_providers(),
        }
