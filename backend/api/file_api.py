"""文件中心与静态文件下载接口。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.db.database import get_db_connection, init_agent_memory_db
from backend.security.ownership_guard import ownership_guard
from backend.security.resource_scope import ResourceScope
from backend.services.file_converter import FileConverterService
from backend.services.file_service import FileCatalogService
from backend.services.ocr import OCRService
from backend.services.rag import RAGService
from backend.services.workspace_manager import DEFAULT_USER_ID, WorkspaceManager
from backend.tasks import get_task_manager
from backend.tasks.task_schema import TaskCreateRequest
from raman_core.methanol.config import PROJECT_ROOT, REPORT_DIR, ensure_dirs


router = APIRouter(prefix="/api/files", tags=["files"])
workspace_manager = WorkspaceManager()
file_catalog = FileCatalogService()
file_converter = FileConverterService()


def _scope(current_user: dict) -> ResourceScope:
    return ResourceScope.from_auth_context(current_user)


class FileConvertRequest(BaseModel):
    file_id: str
    target_format: str
    conversation_id: str
    user_id: str | None = None


class FileOCRRequest(BaseModel):
    conversation_id: str
    user_id: str | None = None
    page_range: str | None = None


def validate_report_file_name(report_file: str) -> str:
    """校验报告文件名，防止路径穿越。"""
    if not report_file:
        raise ValueError("报告文件名不能为空。")
    if any(token in report_file for token in ("..", "/", "\\")):
        raise ValueError("报告文件名不合法。")

    safe_name = Path(report_file).name
    if safe_name != report_file:
        raise ValueError("报告文件名不合法。")
    return safe_name


def error_detail(message: str, *, error_code: str, suggestion: str = "") -> dict:
    return {
        "message": message,
        "error_code": error_code,
        "error_message": message,
        "suggestion": suggestion,
    }


def _append_ocr_chunks(*, file_id: str, file_item: dict, user_id: str, conversation_id: str, pages: list[dict], source_path: Path) -> int:
    init_agent_memory_db()
    now = datetime.now().isoformat(timespec="seconds")
    connection = get_db_connection()
    count = 0
    try:
        for page_item in pages:
            text = str(page_item.get("text") or "").strip()
            if not text:
                continue
            start = 0
            chunk_index = 0
            while start < len(text):
                part = text[start : start + 1800].strip()
                if part:
                    text_hash = hashlib.sha256(part.encode("utf-8", errors="ignore")).hexdigest()
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO file_chunks (
                            chunk_id, user_id, conversation_id, file_id, filename,
                            source_path, page, section, text, token_estimate,
                            metadata_json, created_at, source_type, sheet,
                            chunk_index, text_hash, updated_at, rag_indexed
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"ocr_{uuid4().hex}",
                            user_id,
                            conversation_id,
                            file_id,
                            str(file_item.get("original_filename") or file_item.get("filename") or source_path.name),
                            str(source_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                            str(page_item.get("page") or ""),
                            "ocr",
                            part,
                            max(1, len(part) // 4),
                            json.dumps({"ocr": True, "page": page_item.get("page")}, ensure_ascii=False),
                            now,
                            "ocr",
                            None,
                            chunk_index,
                            text_hash,
                            now,
                            0,
                        ),
                    )
                    count += 1
                    chunk_index += 1
                start += 1800
        connection.commit()
    finally:
        connection.close()
    return count


@router.get("/reports/{report_file}/download")
def download_report(report_file: str):
    """下载 Markdown 报告文件。"""
    ensure_dirs()
    try:
        safe_name = validate_report_file_name(report_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = REPORT_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"报告文件不存在: {safe_name}")

    return FileResponse(
        path=path,
        media_type="text/markdown; charset=utf-8",
        filename=safe_name,
    )


@router.post("/upload")
async def upload_workspace_file(
    file: UploadFile = File(...),
    user_id: str = Form(default=DEFAULT_USER_ID),
    conversation_id: str | None = Form(default=None),
    project_id: str | None = Form(default=None),
    current_user: dict = Depends(get_request_user_context),
) -> dict:
    """上传文件到当前 conversation workspace。"""
    effective_user_id = current_user["user_id"] if current_user.get("authenticated") else user_id
    workspace = workspace_manager.create_workspace(effective_user_id, conversation_id)
    try:
        info = await workspace_manager.save_upload_file(
            workspace["user_id"],
            workspace["conversation_id"],
            file,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": True,
        "user_id": workspace["user_id"],
        "conversation_id": workspace["conversation_id"],
        **info,
    }


@router.post("/convert")
def convert_file(payload: FileConvertRequest, current_user: dict = Depends(get_request_user_context)) -> dict:
    effective_user_id = current_user["user_id"] if current_user.get("authenticated") else (payload.user_id or DEFAULT_USER_ID)
    if current_user.get("authenticated"):
        ownership_guard.require_file_owner(payload.file_id, _scope(current_user), file_catalog=file_catalog)
    try:
        result = file_converter.convert_file(
            file_id=payload.file_id,
            target_format=payload.target_format,
            user_id=effective_user_id,
            conversation_id=payload.conversation_id,
            is_admin=current_user.get("is_admin", False),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail(str(exc), error_code="FILE_NOT_FOUND", suggestion="请刷新文件列表后重试。"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=error_detail(str(exc), error_code="FILE_CONVERT_UNSUPPORTED", suggestion="可以尝试转换为 txt、md、html、docx、csv 或 xlsx。"),
        ) from exc
    return result


@router.post("/{file_id}/ocr")
def run_file_ocr(
    file_id: str,
    payload: FileOCRRequest,
    async_task: bool = Query(default=False),
    current_user: dict = Depends(get_request_user_context),
) -> dict:
    effective_user_id = current_user["user_id"] if current_user.get("authenticated") else (payload.user_id or DEFAULT_USER_ID)
    if current_user.get("authenticated"):
        ownership_guard.require_file_owner(file_id, _scope(current_user), file_catalog=file_catalog)
    if async_task:
        task = get_task_manager().create_task(
            TaskCreateRequest(
                task_type="ocr",
                payload={
                    "file_id": file_id,
                    "conversation_id": payload.conversation_id,
                    "page_range": payload.page_range,
                    "is_admin": current_user["is_admin"],
                },
                user_id=effective_user_id,
                conversation_id=payload.conversation_id,
            )
        )
        return {"success": True, "async_task": True, "task_id": task.get("task_id"), "task": task}
    file_item = file_catalog.get_file_for_user(file_id, user_id=effective_user_id, is_admin=current_user["is_admin"])
    if file_item is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("文件不存在。", error_code="FILE_NOT_FOUND", suggestion="请刷新文件列表后重试。"),
        )
    source_path = (PROJECT_ROOT / str(file_item.get("path") or "")).resolve()
    project_root = PROJECT_ROOT.resolve()
    if source_path != project_root and project_root not in source_path.parents:
        raise HTTPException(
            status_code=400,
            detail=error_detail("文件路径不合法。", error_code="FILE_PATH_INVALID", suggestion="请重新上传文件后重试。"),
        )
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=error_detail("文件已被删除或移动。", error_code="FILE_PATH_MISSING", suggestion="建议重新上传文件。"),
        )

    suffix = source_path.suffix.lower()
    ocr = OCRService()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}:
        result = ocr.extract_image_text(source_path)
    elif suffix == ".pdf":
        result = ocr.extract_pdf_text(source_path, page_range=payload.page_range)
    else:
        raise HTTPException(
            status_code=400,
            detail=error_detail("该文件类型暂不支持 OCR。", error_code="OCR_UNSUPPORTED_FILE_TYPE", suggestion="请上传图片或扫描版 PDF。"),
        )

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=error_detail(str(result.get("error_message") or "OCR 识别失败。"), error_code="OCR_FAILED", suggestion="请检查 OCR_PROVIDER、语言包、pdf2image/Poppler 或图片清晰度。"),
        )

    pages = list(result.get("pages") or [])
    if not pages and str(result.get("text") or "").strip():
        pages = [{"page": 1, "text": result.get("text")}]
    chunk_count = _append_ocr_chunks(
        file_id=file_id,
        file_item=file_item,
        user_id=effective_user_id,
        conversation_id=payload.conversation_id,
        pages=pages,
        source_path=source_path,
    )
    rag_index = RAGService().index_file(file_id, effective_user_id, payload.conversation_id).to_dict() if chunk_count else {"status": "not_supported", "chunk_count": 0}
    return {
        "success": True,
        "file_id": file_id,
        "conversation_id": payload.conversation_id,
        "ocr": {
            "provider": (result.get("status") or {}).get("provider"),
            "language": (result.get("status") or {}).get("language"),
            "character_count": len(str(result.get("text") or "")),
            "page_count": len(pages),
            "chunk_count": chunk_count,
        },
        "rag_index": rag_index,
        "message": f"OCR 完成，新增 {chunk_count} 个文本片段。",
    }


@router.get("")
def list_files(
    user_id: str = Query(default=DEFAULT_USER_ID),
    workspace_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    current_user: dict = Depends(get_request_user_context),
) -> dict:
    effective_user_id = None
    if current_user.get("authenticated"):
        effective_user_id = None if current_user.get("is_admin") and user_id in {"", DEFAULT_USER_ID} else current_user["user_id"]
    else:
        effective_user_id = user_id
    dedupe_result = None
    if workspace_id and effective_user_id:
        dedupe_result = file_catalog.cleanup_workspace_duplicates(workspace_id=workspace_id, user_id=effective_user_id)
        replaced_by = dedupe_result.get("replaced_by") or {}
        if replaced_by:
            active_files = workspace_manager.read_active_files(effective_user_id, workspace_id)
            normalized_active = []
            seen_file_ids: set[str] = set()
            for item in active_files:
                file_id = str((item or {}).get("file_id") or "").strip()
                if not file_id:
                    continue
                file_id = str(replaced_by.get(file_id) or file_id)
                if file_id in seen_file_ids:
                    continue
                refreshed = file_catalog.get_file_for_user(file_id, user_id=effective_user_id, is_admin=current_user.get("is_admin", False))
                if refreshed is not None:
                    normalized_active.append(refreshed)
                    seen_file_ids.add(file_id)
            workspace_manager.update_active_files(effective_user_id, workspace_id, normalized_active[-20:])
    files = file_catalog.list_files(user_id=effective_user_id, workspace_id=workspace_id, project_id=project_id)
    return {
        "success": True,
        "files": files,
        "total": len(files),
        "deduplicated": bool(dedupe_result and dedupe_result.get("changed")),
        "removed_duplicates": len((dedupe_result or {}).get("removed_files") or []),
    }


@router.get("/{file_id}")
def get_file(file_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    file_item = ownership_guard.require_file_owner(file_id, _scope(current_user), file_catalog=file_catalog) if current_user.get("authenticated") else file_catalog.get_file_for_user(file_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    if file_item is None:
        raise HTTPException(status_code=404, detail=error_detail("文件不存在。", error_code="FILE_NOT_FOUND", suggestion="请刷新文件列表后重试。"))
    return {"success": True, "file": file_item}


@router.get("/{file_id}/download")
def download_file(file_id: str, current_user: dict = Depends(get_request_user_context)):
    file_item = ownership_guard.require_file_owner(file_id, _scope(current_user), file_catalog=file_catalog) if current_user.get("authenticated") else file_catalog.get_file_for_user(file_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    if file_item is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("文件不存在。", error_code="FILE_NOT_FOUND", suggestion="请刷新文件中心后重试。"),
        )
    path = Path(PROJECT_ROOT / str(file_item.get("path") or "")).resolve()
    project_root = PROJECT_ROOT.resolve()
    if path != project_root and project_root not in path.parents:
        raise HTTPException(
            status_code=400,
            detail=error_detail("文件路径不合法。", error_code="FILE_PATH_INVALID", suggestion="请刷新文件列表后重试。"),
        )
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=error_detail("文件已被删除或移动。", error_code="FILE_PATH_MISSING", suggestion="建议重新上传或重新生成文件。"),
        )
    return FileResponse(
        path=path,
        filename=file_catalog.build_download_name(file_item),
        media_type=str(file_item.get("mime_type") or "application/octet-stream"),
    )


@router.delete("/{file_id}")
def delete_file(file_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        file_item = ownership_guard.require_file_owner(file_id, _scope(current_user), file_catalog=file_catalog) if current_user.get("authenticated") else file_catalog.get_file_for_user(file_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
        if file_item is None:
            raise KeyError(file_id)
        deleted = file_catalog.delete_file(file_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail("文件不存在。", error_code="FILE_NOT_FOUND", suggestion="请刷新文件列表确认文件是否仍存在。"),
        ) from exc
    return {
        "success": True,
        "message": "文件已删除。",
        "file": deleted,
    }


@router.get("/{file_id}/preview")
def preview_file(file_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        file_item = ownership_guard.require_file_owner(file_id, _scope(current_user), file_catalog=file_catalog) if current_user.get("authenticated") else file_catalog.get_file_for_user(file_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
        if file_item is None:
            raise KeyError(file_id)
        return file_catalog.preview_file(file_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail("文件不存在。", error_code="FILE_NOT_FOUND", suggestion="请刷新文件中心后重试。"),
        ) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=error_detail("该文件无法按文本方式预览。", error_code="FILE_PREVIEW_UNSUPPORTED", suggestion="请直接下载查看原文件。"),
        ) from exc


@router.post("/{file_id}/activate")
def activate_file(
    file_id: str,
    user_id: str = Form(default=DEFAULT_USER_ID),
    conversation_id: str = Form(...),
    current_user: dict = Depends(get_request_user_context),
) -> dict:
    effective_user_id = current_user["user_id"] if current_user.get("authenticated") else user_id
    file_item = ownership_guard.require_file_owner(file_id, _scope(current_user), file_catalog=file_catalog) if current_user.get("authenticated") else file_catalog.get_file_for_user(file_id, user_id=effective_user_id, is_admin=current_user["is_admin"])
    if file_item is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("文件不存在。", error_code="FILE_NOT_FOUND", suggestion="请先刷新文件列表。"),
        )
    active_files = workspace_manager.read_active_files(effective_user_id, conversation_id)
    active_files = [item for item in active_files if item.get("file_id") != file_id]
    active_files.append(file_item)
    workspace_manager.update_active_files(effective_user_id, conversation_id, active_files[-20:])
    return {
        "success": True,
        "message": "文件已设为当前分析对象。",
        "file": file_item,
        "conversation_id": conversation_id,
    }
