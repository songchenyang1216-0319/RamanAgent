from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from backend.db.database import get_db_connection, init_agent_memory_db
from backend.services.file_processor import FileProcessorRegistry
from backend.services.workspace_manager import safe_filename, safe_segment
from raman_core.methanol.config import PROJECT_ROOT

from .knowledge_base_indexer import KnowledgeBaseIndexer
from .knowledge_base_service import KnowledgeBaseService


KB_ROOT = PROJECT_ROOT / "storage" / "knowledge_bases"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class KnowledgeBaseFileService:
    def __init__(self) -> None:
        self.kb_service = KnowledgeBaseService()
        self.processors = FileProcessorRegistry()
        self.indexer = KnowledgeBaseIndexer()

    async def upload_file_to_knowledge_base(self, user_id: str, knowledge_base_id: str, file: UploadFile, *, is_admin: bool = False) -> dict[str, Any]:
        kb = self.kb_service.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)
        if not self.kb_service.permissions.can_write(kb, user_id, is_admin=is_admin):
            raise PermissionError("无权上传知识库文件。")
        owner = safe_segment(str(kb["owner_user_id"]))
        kb_segment = safe_segment(knowledge_base_id)
        source_dir = KB_ROOT / owner / kb_segment / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        original_name = file.filename or "knowledge-file.bin"
        safe_name = safe_filename(original_name, fallback="knowledge-file")
        target = source_dir / f"{Path(safe_name).stem}_{uuid4().hex[:8]}{Path(safe_name).suffix}"
        content = await file.read()
        if not content:
            raise ValueError("上传文件为空。")
        target.write_bytes(content)
        kb_file_id = f"kbf_{uuid4().hex[:12]}"
        stored_path = str(target.relative_to(PROJECT_ROOT)).replace("\\", "/")
        processed = self.processors.get_processor(target).process(target, file_id=kb_file_id).to_dict() if self.processors.get_processor(target) else {"success": False, "error_message": "当前文件类型暂不支持解析。", "chunks": [], "file_type": target.suffix.lower().lstrip(".")}
        chunk_count = 0
        processing_status = "success" if processed.get("success") else "failed"
        rag_index_status = "not_supported"
        rag_index_error = processed.get("error_message")
        if processed.get("success") and processed.get("chunks"):
            chunk_count = self.indexer.store_processed_chunks(
                owner_user_id=str(kb["owner_user_id"]),
                knowledge_base_id=knowledge_base_id,
                kb_file_id=kb_file_id,
                source_name=original_name,
                source_type=str(processed.get("file_type") or target.suffix.lower().lstrip(".")),
                chunks=list(processed.get("chunks") or []),
            )
            index_result = self.indexer.index_knowledge_base_file(
                owner_user_id=str(kb["owner_user_id"]),
                knowledge_base_id=knowledge_base_id,
                kb_file_id=kb_file_id,
                knowledge_base_name=str(kb.get("name") or ""),
            )
            rag_index_status = str(index_result.get("status") or "failed")
            rag_index_error = index_result.get("error_message")
        self._insert_file(
            kb_file_id=kb_file_id,
            knowledge_base_id=knowledge_base_id,
            owner_user_id=str(kb["owner_user_id"]),
            original_filename=original_name,
            stored_path=stored_path,
            file_type=target.suffix.lower().lstrip("."),
            mime_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            size=target.stat().st_size,
            processing_status=processing_status,
            rag_index_status=rag_index_status,
            rag_index_error=rag_index_error,
            chunk_count=chunk_count,
        )
        item = self.get_knowledge_base_file(user_id, knowledge_base_id, kb_file_id, is_admin=is_admin)
        item["processing"] = processed
        return item

    def list_knowledge_base_files(self, user_id: str, knowledge_base_id: str, *, is_admin: bool = False) -> list[dict[str, Any]]:
        self.kb_service.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM knowledge_base_files WHERE knowledge_base_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC",
                (knowledge_base_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def get_knowledge_base_file(self, user_id: str, knowledge_base_id: str, kb_file_id: str, *, is_admin: bool = False) -> dict[str, Any]:
        self.kb_service.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)
        connection = get_db_connection()
        try:
            row = connection.execute(
                "SELECT * FROM knowledge_base_files WHERE knowledge_base_id = ? AND kb_file_id = ? AND deleted_at IS NULL",
                (knowledge_base_id, kb_file_id),
            ).fetchone()
            if not row:
                raise KeyError(kb_file_id)
            return dict(row)
        finally:
            connection.close()

    def delete_knowledge_base_file(self, user_id: str, knowledge_base_id: str, kb_file_id: str, *, is_admin: bool = False) -> dict[str, Any]:
        kb = self.kb_service.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)
        if not self.kb_service.permissions.can_write(kb, user_id, is_admin=is_admin):
            raise PermissionError("无权删除知识库文件。")
        item = self.get_knowledge_base_file(user_id, knowledge_base_id, kb_file_id, is_admin=is_admin)
        now = now_iso()
        connection = get_db_connection()
        try:
            connection.execute("UPDATE knowledge_base_files SET deleted_at = ?, updated_at = ?, rag_index_status = 'deleted' WHERE kb_file_id = ?", (now, now, kb_file_id))
            connection.execute("DELETE FROM knowledge_base_chunks WHERE knowledge_base_id = ? AND kb_file_id = ?", (knowledge_base_id, kb_file_id))
            connection.commit()
        finally:
            connection.close()
        self.indexer.delete_knowledge_base_vectors(knowledge_base_id, kb_file_id)
        return item

    def _insert_file(self, **payload: Any) -> None:
        init_agent_memory_db()
        now = now_iso()
        connection = get_db_connection()
        try:
            connection.execute(
                """
                INSERT INTO knowledge_base_files (
                    kb_file_id, knowledge_base_id, owner_user_id, original_filename,
                    stored_path, file_type, mime_type, size, processing_status,
                    rag_index_status, rag_index_error, chunk_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["kb_file_id"],
                    payload["knowledge_base_id"],
                    payload["owner_user_id"],
                    payload["original_filename"],
                    payload["stored_path"],
                    payload["file_type"],
                    payload["mime_type"],
                    payload["size"],
                    payload["processing_status"],
                    payload["rag_index_status"],
                    payload["rag_index_error"],
                    payload["chunk_count"],
                    now,
                    now,
                ),
            )
            connection.commit()
        finally:
            connection.close()
