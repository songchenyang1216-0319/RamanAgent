from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from backend.db.database import get_db_connection, init_agent_memory_db
from backend.services.rag import RAGService
from backend.services.rag.schemas import DocumentChunk


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class KnowledgeBaseIndexer:
    def __init__(self) -> None:
        self.rag_service = RAGService()

    def store_processed_chunks(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        kb_file_id: str,
        source_name: str,
        source_type: str,
        chunks: list[dict[str, Any]],
    ) -> int:
        init_agent_memory_db()
        now = now_iso()
        connection = get_db_connection()
        try:
            connection.execute("DELETE FROM knowledge_base_chunks WHERE knowledge_base_id = ? AND kb_file_id = ?", (knowledge_base_id, kb_file_id))
            for index, chunk in enumerate(chunks):
                text = str(chunk.get("text") or "").strip()
                if not text:
                    continue
                text_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
                connection.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_base_chunks (
                        chunk_id, knowledge_base_id, kb_file_id, owner_user_id, source_name,
                        source_type, text, page, sheet, section, chunk_index,
                        text_hash, rag_indexed, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        str(chunk.get("chunk_id") or hashlib.sha1(f"{kb_file_id}:{index}:{text[:80]}".encode("utf-8", errors="ignore")).hexdigest()),
                        knowledge_base_id,
                        kb_file_id,
                        owner_user_id,
                        source_name,
                        source_type,
                        text,
                        chunk.get("page"),
                        chunk.get("sheet"),
                        chunk.get("section"),
                        int(chunk.get("chunk_index") or index),
                        text_hash,
                        now,
                        now,
                    ),
                )
            connection.commit()
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM knowledge_base_chunks WHERE knowledge_base_id = ? AND kb_file_id = ?",
                (knowledge_base_id, kb_file_id),
            ).fetchone()
            return int(row["count"] if row else 0)
        finally:
            connection.close()

    def index_knowledge_base_file(self, *, owner_user_id: str, knowledge_base_id: str, kb_file_id: str, knowledge_base_name: str = "") -> dict[str, Any]:
        chunks = self._load_chunks(owner_user_id=owner_user_id, knowledge_base_id=knowledge_base_id, kb_file_id=kb_file_id, knowledge_base_name=knowledge_base_name)
        result = self.rag_service.index_knowledge_base_chunks(chunks, owner_user_id=owner_user_id, knowledge_base_id=knowledge_base_id, kb_file_id=kb_file_id)
        return result.to_dict()

    def rebuild_knowledge_base_index(self, *, owner_user_id: str, knowledge_base_id: str, knowledge_base_name: str = "") -> dict[str, Any]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT DISTINCT kb_file_id FROM knowledge_base_chunks WHERE owner_user_id = ? AND knowledge_base_id = ?",
                (owner_user_id, knowledge_base_id),
            ).fetchall()
        finally:
            connection.close()
        results = [
            self.index_knowledge_base_file(owner_user_id=owner_user_id, knowledge_base_id=knowledge_base_id, kb_file_id=str(row["kb_file_id"]), knowledge_base_name=knowledge_base_name)
            for row in rows
        ]
        return {"success": True, "results": results, "total": len(results)}

    def get_knowledge_base_index_status(self, *, owner_user_id: str, knowledge_base_id: str) -> dict[str, Any]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            file_rows = connection.execute(
                """
                SELECT processing_status, rag_index_status, rag_index_error, chunk_count
                FROM knowledge_base_files
                WHERE owner_user_id = ? AND knowledge_base_id = ? AND deleted_at IS NULL
                """,
                (owner_user_id, knowledge_base_id),
            ).fetchall()
            chunk_row = connection.execute(
                "SELECT COUNT(*) AS count, SUM(CASE WHEN rag_indexed = 1 THEN 1 ELSE 0 END) AS indexed_count FROM knowledge_base_chunks WHERE owner_user_id = ? AND knowledge_base_id = ?",
                (owner_user_id, knowledge_base_id),
            ).fetchone()
            latest_index = connection.execute(
                """
                SELECT status, error_message, updated_at, embedding_provider, embedding_model, vector_provider
                FROM rag_indexes
                WHERE rag_scope = 'knowledge_base' AND user_id = ? AND knowledge_base_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (owner_user_id, knowledge_base_id),
            ).fetchone()
        finally:
            connection.close()

        file_count = len(file_rows)
        chunk_count = int(chunk_row["count"] or 0) if chunk_row else 0
        indexed_chunk_count = int(chunk_row["indexed_count"] or 0) if chunk_row else 0
        failed_files = [dict(row) for row in file_rows if str(row["processing_status"] or "").lower() == "failed" or str(row["rag_index_status"] or "").lower() == "failed"]
        pending_files = [dict(row) for row in file_rows if str(row["rag_index_status"] or "").lower() in {"pending", "running", ""}]
        latest = dict(latest_index) if latest_index else {}
        if failed_files:
            status = "failed"
        elif pending_files:
            status = "pending"
        elif chunk_count and indexed_chunk_count >= chunk_count:
            status = "indexed"
        elif chunk_count:
            status = "partial"
        elif file_count:
            status = "not_supported"
        else:
            status = "empty"
        return {
            "success": True,
            "knowledge_base_id": knowledge_base_id,
            "owner_user_id": owner_user_id,
            "status": status,
            "file_count": file_count,
            "chunk_count": chunk_count,
            "indexed_chunk_count": indexed_chunk_count,
            "failed_file_count": len(failed_files),
            "pending_file_count": len(pending_files),
            "latest_index": latest,
            "error_message": latest.get("error_message") or (failed_files[0].get("rag_index_error") if failed_files else None),
        }

    def delete_knowledge_base_vectors(self, knowledge_base_id: str, kb_file_id: str | None = None) -> None:
        if kb_file_id:
            self.rag_service.vector_store.delete_by_knowledge_base_file(knowledge_base_id, kb_file_id)
        else:
            self.rag_service.vector_store.delete_by_knowledge_base(knowledge_base_id)

    def _load_chunks(self, *, owner_user_id: str, knowledge_base_id: str, kb_file_id: str, knowledge_base_name: str) -> list[DocumentChunk]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM knowledge_base_chunks WHERE owner_user_id = ? AND knowledge_base_id = ? AND kb_file_id = ? ORDER BY id ASC",
                (owner_user_id, knowledge_base_id, kb_file_id),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                result.append(
                    DocumentChunk(
                        chunk_id=str(item["chunk_id"]),
                        file_id=None,
                        conversation_id=None,
                        user_id=owner_user_id,
                        filename=str(item.get("source_name") or ""),
                        source_type=str(item.get("source_type") or "knowledge_base"),
                        text=str(item.get("text") or ""),
                        page=item.get("page"),
                        sheet=item.get("sheet"),
                        section=item.get("section"),
                        chunk_index=int(item.get("chunk_index") or 0),
                        metadata={"text_hash": item.get("text_hash")},
                        rag_scope="knowledge_base",
                        knowledge_base_id=knowledge_base_id,
                        knowledge_base_name=knowledge_base_name,
                        kb_file_id=kb_file_id,
                        source_group="knowledge_base",
                    )
                )
            return result
        finally:
            connection.close()
