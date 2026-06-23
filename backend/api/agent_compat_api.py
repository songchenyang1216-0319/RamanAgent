from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend.agent.agent_router import (
    _build_session_memory_response,
    model_registry_service,
)
from backend.api.deprecation import apply_deprecation_headers
from backend.agent.session_store import clear_session_memory, create_session, get_session
from backend.services.methanol_service import reset_predictor_cache


router = APIRouter(prefix="/api/agent", tags=["agent-compat"])


class SwitchAgentModelRequest(BaseModel):
    model_name: str


@router.get("/models")
def get_agent_models(response: Response) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/models", successor_path="/api/models/providers")
    result = model_registry_service.list_models_for_agent()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error_message"])
    return result["data"]


@router.patch("/models/current")
def switch_agent_model(payload: SwitchAgentModelRequest, response: Response) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/models/current", successor_path="/api/models/select")
    result = model_registry_service.switch_current_model_for_agent(payload.model_name)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error_message"])
    reset_predictor_cache()
    return {
        "success": True,
        "current_model": result["current_model"],
        "message": result["message"],
        "warnings": result.get("warnings") or [],
    }


@router.post("/session/new")
def create_new_session(response: Response) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/session/new", successor_path="/api/conversations")
    session = create_session()
    return {
        "success": True,
        "session_id": session["session_id"],
    }


@router.get("/session/{session_id}")
def get_session_memory(session_id: str, response: Response) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/session/{session_id}", successor_path="/api/conversations/{conversation_id}")
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="未找到对应的会话。")
    payload = _build_session_memory_response(session_id)
    payload["success"] = True
    return payload


@router.post("/session/{session_id}/clear")
def clear_session(session_id: str, response: Response) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/session/{session_id}/clear", successor_path="/api/conversations/{conversation_id}")
    try:
        session = clear_session_memory(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = _build_session_memory_response(str(session.get("session_id") or session_id))
    payload["success"] = True
    payload["message"] = "当前会话记忆已清空。"
    return payload
