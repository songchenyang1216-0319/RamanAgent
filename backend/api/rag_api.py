from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.services.file_service import FileCatalogService
from backend.services.knowledge_base import KnowledgeBaseService
from backend.services.rag import RAGService
from backend.services.workspace_manager import DEFAULT_USER_ID


router = APIRouter(prefix="/api/rag", tags=["rag"])
rag_service = RAGService()
file_catalog = FileCatalogService()
kb_service = KnowledgeBaseService()


def _effective_user_id(current_user: dict, requested_user_id: str | None = None) -> str:
    if current_user.get("authenticated"):
        return str(current_user["user_id"])
    return str(requested_user_id or DEFAULT_USER_ID)


class RAGIndexFileRequest(BaseModel):
    conversation_id: str
    file_id: str | None = None
    file_ids: list[str] = []
    user_id: str | None = None


class RAGQueryRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    file_ids: list[str] = []
    knowledge_base_ids: list[str] = []
    rag_scope: str = "conversation"
    top_k: int | None = None
    answer: bool = True
    user_id: str | None = None


class RAGRebuildAllRequest(BaseModel):
    user_id: str | None = None


@router.post("/index-file")
def index_file(payload: RAGIndexFileRequest, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, payload.user_id)
    file_ids = list(payload.file_ids or [])
    if payload.file_id:
        file_ids.insert(0, payload.file_id)
    file_ids = [item for index, item in enumerate(file_ids) if item and item not in file_ids[:index]]
    if not file_ids:
        raise HTTPException(status_code=400, detail={"error_code": "RAG_FILE_REQUIRED", "error_message": "请提供 file_id 或 file_ids。"})
    missing = []
    for file_id in file_ids:
        if file_catalog.get_file_for_user(file_id, user_id=effective_user, is_admin=current_user.get("is_admin", False)) is None:
            missing.append(file_id)
    if missing:
        raise HTTPException(status_code=404, detail={"error_code": "RAG_FILE_NOT_FOUND", "error_message": f"文件不存在或无权访问: {', '.join(missing)}"})
    results = rag_service.index_files(file_ids, effective_user, payload.conversation_id)
    return {"success": True, "results": [item.to_dict() for item in results], "total": len(results)}


@router.post("/rebuild-all")
def rebuild_all_indexes(payload: RAGRebuildAllRequest | None = None, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    payload = payload or RAGRebuildAllRequest()
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail={"error_code": "RAG_ADMIN_REQUIRED", "error_message": "全量重建索引需要管理员权限。"})
    effective_user = _effective_user_id(current_user, payload.user_id)
    return rag_service.rebuild_all_indexes(effective_user)


@router.post("/rebuild-conversation-index")
def rebuild_conversation_index(payload: RAGIndexFileRequest, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, payload.user_id)
    return rag_service.rebuild_conversation_index(effective_user, payload.conversation_id)


@router.post("/query")
def query_rag(payload: RAGQueryRequest, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, payload.user_id)
    rag_scope = payload.rag_scope if payload.rag_scope in {"conversation", "knowledge_base", "mixed"} else "conversation"
    conversation_id = payload.conversation_id or ""
    file_ids = list(payload.file_ids or [])
    knowledge_base_ids = list(payload.knowledge_base_ids or [])
    if file_ids:
        allowed_files = file_catalog.get_files_by_ids(file_ids, user_id=effective_user, is_admin=current_user.get("is_admin", False))
        allowed_ids = {str(item.get("file_id")) for item in allowed_files}
        denied = [file_id for file_id in file_ids if file_id not in allowed_ids]
        if denied:
            raise HTTPException(status_code=404, detail={"error_code": "RAG_FILE_NOT_FOUND", "error_message": f"文件不存在或无权访问: {', '.join(denied)}"})
    if rag_scope in {"knowledge_base", "mixed"}:
        if not knowledge_base_ids:
            knowledge_base_ids = kb_service.authorized_enabled_ids(effective_user, is_admin=current_user.get("is_admin", False), conversation_id=conversation_id)
        for kb_id in knowledge_base_ids:
            try:
                kb_service.get_knowledge_base(effective_user, kb_id, is_admin=current_user.get("is_admin", False))
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail={"error_code": "KB_FORBIDDEN", "error_message": str(exc)}) from exc
    if payload.answer:
        answer = rag_service.answer_with_rag(
            payload.query,
            effective_user,
            conversation_id,
            file_ids=file_ids,
            knowledge_base_ids=knowledge_base_ids,
            rag_scope=rag_scope,
        )
        return answer.to_dict()
    result = rag_service.search(
        payload.query,
        effective_user,
        conversation_id,
        file_ids=file_ids,
        knowledge_base_ids=knowledge_base_ids,
        top_k=payload.top_k,
        rag_scope=rag_scope,
    )
    return result.to_dict()


@router.get("/health")
def rag_health(
    conversation_id: str | None = Query(default=None),
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    return rag_service.health(user_id=effective_user, conversation_id=conversation_id)


@router.get("/status")
def rag_status(
    conversation_id: str | None = Query(default=None),
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    stats = rag_service.vector_store.get_stats()
    enabled_kbs = kb_service.authorized_enabled_ids(effective_user, is_admin=current_user.get("is_admin", False), conversation_id=conversation_id)
    return {
        "success": True,
        "rag_enabled": rag_service.enabled(),
        "vector_store": stats,
        "embedding": rag_service.embedding_service.get_model_info(),
        "conversation_id": conversation_id,
        "available_knowledge_base_ids": enabled_kbs,
    }
