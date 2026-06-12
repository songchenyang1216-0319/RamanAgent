from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.services.knowledge_base import KnowledgeBaseFileService, KnowledgeBaseIndexer, KnowledgeBaseService
from backend.services.rag import RAGService
from backend.services.workspace_manager import DEFAULT_USER_ID


router = APIRouter(prefix="/api", tags=["knowledge-bases"])
kb_service = KnowledgeBaseService()
kb_file_service = KnowledgeBaseFileService()


def _effective_user_id(current_user: dict, requested_user_id: str | None = None) -> str:
    if current_user.get("authenticated"):
        return str(current_user["user_id"])
    return str(requested_user_id or DEFAULT_USER_ID)


def _handle_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail={"error_code": "KB_FORBIDDEN", "error_message": str(exc), "message": str(exc)})
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail={"error_code": "KB_NOT_FOUND", "error_message": str(exc), "message": "知识库或文件不存在。"})
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail={"error_code": "KB_BAD_REQUEST", "error_message": str(exc), "message": str(exc)})
    return HTTPException(status_code=500, detail={"error_code": "KB_INTERNAL_ERROR", "error_message": str(exc), "message": "知识库操作失败。"})


class KnowledgeBaseCreateRequest(BaseModel):
    name: str
    description: str = ""
    visibility: str = "private"
    user_id: str | None = None


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    visibility: str | None = None
    enabled: bool | None = None
    user_id: str | None = None


class ConversationKnowledgeBaseRequest(BaseModel):
    knowledge_base_id: str
    enabled: bool = True
    user_id: str | None = None


class KnowledgeBaseSearchRequest(BaseModel):
    query: str
    top_k: int | None = None
    user_id: str | None = None


@router.get("/knowledge-bases")
def list_knowledge_bases(
    user_id: str = Query(default=DEFAULT_USER_ID),
    include_disabled: bool = Query(default=True),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    items = kb_service.list_knowledge_bases(effective_user, is_admin=current_user.get("is_admin", False), include_disabled=include_disabled)
    return {"success": True, "knowledge_bases": items, "total": len(items)}


@router.post("/knowledge-bases")
def create_knowledge_base(payload: KnowledgeBaseCreateRequest, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, payload.user_id)
    try:
        kb = kb_service.create_knowledge_base(effective_user, payload.name, payload.description, payload.visibility)
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"success": True, "knowledge_base": kb}


@router.get("/knowledge-bases/{knowledge_base_id}")
def get_knowledge_base(
    knowledge_base_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    try:
        kb = kb_service.get_knowledge_base(effective_user, knowledge_base_id, is_admin=current_user.get("is_admin", False))
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"success": True, "knowledge_base": kb}


@router.patch("/knowledge-bases/{knowledge_base_id}")
def update_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdateRequest,
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, payload.user_id)
    try:
        kb = kb_service.update_knowledge_base(
            effective_user,
            knowledge_base_id,
            name=payload.name,
            description=payload.description,
            visibility=payload.visibility,
            is_admin=current_user.get("is_admin", False),
        )
        if payload.enabled is not None:
            kb = kb_service.enable_knowledge_base(effective_user, knowledge_base_id, enabled=payload.enabled, is_admin=current_user.get("is_admin", False))
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"success": True, "knowledge_base": kb}


@router.delete("/knowledge-bases/{knowledge_base_id}")
def delete_knowledge_base(
    knowledge_base_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    try:
        kb = kb_service.delete_knowledge_base(effective_user, knowledge_base_id, is_admin=current_user.get("is_admin", False))
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"success": True, "knowledge_base": kb}


@router.get("/knowledge-bases/{knowledge_base_id}/files")
def list_knowledge_base_files(
    knowledge_base_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    try:
        files = kb_file_service.list_knowledge_base_files(effective_user, knowledge_base_id, is_admin=current_user.get("is_admin", False))
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"success": True, "files": files, "total": len(files)}


@router.post("/knowledge-bases/{knowledge_base_id}/files")
async def upload_knowledge_base_file(
    knowledge_base_id: str,
    file: UploadFile = File(...),
    user_id: str = Form(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    try:
        item = await kb_file_service.upload_file_to_knowledge_base(effective_user, knowledge_base_id, file, is_admin=current_user.get("is_admin", False))
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"success": True, "file": item}


@router.delete("/knowledge-bases/{knowledge_base_id}/files/{kb_file_id}")
def delete_knowledge_base_file(
    knowledge_base_id: str,
    kb_file_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    try:
        item = kb_file_service.delete_knowledge_base_file(effective_user, knowledge_base_id, kb_file_id, is_admin=current_user.get("is_admin", False))
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"success": True, "file": item}


@router.post("/knowledge-bases/{knowledge_base_id}/reindex")
def reindex_knowledge_base(
    knowledge_base_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    try:
        kb = kb_service.get_knowledge_base(effective_user, knowledge_base_id, is_admin=current_user.get("is_admin", False))
        if not kb_service.permissions.can_write(kb, effective_user, is_admin=current_user.get("is_admin", False)):
            raise PermissionError("无权重建该知识库索引。")
        result = KnowledgeBaseIndexer().rebuild_knowledge_base_index(
            owner_user_id=str(kb["owner_user_id"]),
            knowledge_base_id=knowledge_base_id,
            knowledge_base_name=str(kb.get("name") or ""),
        )
    except Exception as exc:
        raise _handle_error(exc) from exc
    return result


@router.post("/knowledge-bases/{knowledge_base_id}/rebuild-index")
def rebuild_knowledge_base_index(
    knowledge_base_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    return reindex_knowledge_base(knowledge_base_id, user_id=user_id, current_user=current_user)


@router.get("/knowledge-bases/{knowledge_base_id}/index-status")
def get_knowledge_base_index_status(
    knowledge_base_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    try:
        kb = kb_service.get_knowledge_base(effective_user, knowledge_base_id, is_admin=current_user.get("is_admin", False))
        status = KnowledgeBaseIndexer().get_knowledge_base_index_status(
            owner_user_id=str(kb["owner_user_id"]),
            knowledge_base_id=knowledge_base_id,
        )
    except Exception as exc:
        raise _handle_error(exc) from exc
    return {"success": True, "index_status": status}


@router.post("/knowledge-bases/{knowledge_base_id}/search")
def search_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseSearchRequest,
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, payload.user_id)
    try:
        kb_service.get_knowledge_base(effective_user, knowledge_base_id, is_admin=current_user.get("is_admin", False))
        result = RAGService().search(
            payload.query,
            effective_user,
            "",
            knowledge_base_ids=[knowledge_base_id],
            top_k=payload.top_k,
            rag_scope="knowledge_base",
        )
    except Exception as exc:
        raise _handle_error(exc) from exc
    return result.to_dict()


@router.get("/conversations/{conversation_id}/knowledge-bases")
def list_conversation_knowledge_bases(
    conversation_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    items = kb_service.list_conversation_knowledge_bases(effective_user, conversation_id, is_admin=current_user.get("is_admin", False), enabled_only=False)
    return {"success": True, "knowledge_bases": items, "total": len(items)}


@router.post("/conversations/{conversation_id}/knowledge-bases")
def bind_conversation_knowledge_base(
    conversation_id: str,
    payload: ConversationKnowledgeBaseRequest,
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, payload.user_id)
    try:
        result = kb_service.bind_to_conversation(
            effective_user,
            conversation_id,
            payload.knowledge_base_id,
            enabled=payload.enabled,
            is_admin=current_user.get("is_admin", False),
        )
    except Exception as exc:
        raise _handle_error(exc) from exc
    return result


@router.delete("/conversations/{conversation_id}/knowledge-bases/{knowledge_base_id}")
def unbind_conversation_knowledge_base(
    conversation_id: str,
    knowledge_base_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user = _effective_user_id(current_user, user_id)
    try:
        result = kb_service.unbind_from_conversation(
            effective_user,
            conversation_id,
            knowledge_base_id,
            is_admin=current_user.get("is_admin", False),
        )
    except Exception as exc:
        raise _handle_error(exc) from exc
    return result
