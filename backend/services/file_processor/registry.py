from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.db.database import get_db_connection, init_agent_memory_db

from .archive_processor import ArchiveFileProcessor
from .base import BaseFileProcessor, ProcessedFile
from .code_processor import CodeFileProcessor
from .csv_processor import CsvFileProcessor
from .docx_processor import DocxFileProcessor
from .excel_processor import ExcelFileProcessor
from .image_processor import ImageFileProcessor
from .json_processor import JsonFileProcessor
from .markdown_processor import MarkdownFileProcessor
from .pdf_processor import PdfFileProcessor
from .pptx_processor import PptxFileProcessor
from .text_processor import TextFileProcessor


class FileProcessorRegistry:
    def __init__(self, processors: list[BaseFileProcessor] | None = None) -> None:
        self.processors = processors or [
            TextFileProcessor(),
            MarkdownFileProcessor(),
            JsonFileProcessor(),
            CsvFileProcessor(),
            ExcelFileProcessor(),
            PdfFileProcessor(),
            DocxFileProcessor(),
            PptxFileProcessor(),
            ImageFileProcessor(),
            CodeFileProcessor(),
            ArchiveFileProcessor(),
        ]

    def get_processor(self, path: str | Path) -> BaseFileProcessor | None:
        file_path = Path(path)
        for processor in self.processors:
            if processor.can_process(file_path):
                return processor
        return None

    def supported_suffixes(self) -> list[str]:
        suffixes = sorted({suffix for processor in self.processors for suffix in processor.supported_suffixes})
        return suffixes

    def process(
        self,
        path: str | Path,
        *,
        file_id: str | None = None,
        user_id: str = "default_user",
        conversation_id: str = "",
    ) -> ProcessedFile:
        file_path = Path(path)
        processor = self.get_processor(file_path)
        if processor is None:
            return ProcessedFile(
                success=False,
                file_type="unsupported",
                filename=file_path.name,
                summary="当前文件类型暂未支持自动解析。",
                metadata={"suffix": file_path.suffix.lower(), "supported_suffixes": self.supported_suffixes()},
                error_message="当前文件类型暂未支持自动解析。",
            )
        result = processor.process(file_path, file_id=file_id, user_id=user_id, conversation_id=conversation_id)
        if result.success and result.chunks:
            self.store_chunks(result, user_id=user_id, conversation_id=conversation_id, file_id=file_id, source_path=str(file_path))
        return result

    def store_chunks(
        self,
        result: ProcessedFile,
        *,
        user_id: str,
        conversation_id: str,
        file_id: str | None,
        source_path: str,
    ) -> None:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            if file_id:
                connection.execute(
                    "DELETE FROM file_chunks WHERE user_id = ? AND conversation_id = ? AND file_id = ?",
                    (user_id, conversation_id, file_id),
                )
            now = datetime.now().isoformat(timespec="seconds")
            for index, chunk in enumerate(result.chunks):
                chunk_index = int((chunk.metadata or {}).get("chunk_index") or index)
                text_hash = hashlib.sha256(str(chunk.text or "").encode("utf-8", errors="ignore")).hexdigest()
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
                        chunk.chunk_id,
                        user_id,
                        conversation_id,
                        file_id,
                        result.filename,
                        source_path,
                        chunk.page,
                        chunk.section,
                        chunk.text,
                        chunk.token_estimate,
                        json.dumps(chunk.metadata, ensure_ascii=False),
                        now,
                        result.file_type,
                        (chunk.metadata or {}).get("sheet"),
                        chunk_index,
                        text_hash,
                        now,
                        0,
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def search_chunks(
        self,
        *,
        user_id: str,
        conversation_id: str,
        query: str,
        file_ids: list[str] | None = None,
        source_path: str | None = None,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        init_agent_memory_db()
        tokens = [token for token in str(query or "").lower().split() if token]
        like_terms = [f"%{token}%" for token in tokens[:5]]
        connection = get_db_connection()
        try:
            sql = """
                SELECT * FROM file_chunks
                WHERE user_id = ? AND conversation_id = ?
            """
            params: list[Any] = [user_id, conversation_id]
            if file_ids:
                placeholders = ",".join("?" for _ in file_ids)
                sql += f" AND file_id IN ({placeholders})"
                params.extend(file_ids)
            if source_path:
                sql += " AND source_path = ?"
                params.append(str(source_path))
            if like_terms:
                sql += " AND (" + " OR ".join("LOWER(text) LIKE ?" for _ in like_terms) + ")"
                params.extend(like_terms)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, min(int(limit or 6), 20)))
            rows = connection.execute(sql, params).fetchall()
            if rows or not like_terms:
                return [dict(row) for row in rows]

            fallback_sql = """
                SELECT * FROM file_chunks
                WHERE user_id = ? AND conversation_id = ?
            """
            fallback_params: list[Any] = [user_id, conversation_id]
            if file_ids:
                placeholders = ",".join("?" for _ in file_ids)
                fallback_sql += f" AND file_id IN ({placeholders})"
                fallback_params.extend(file_ids)
            if source_path:
                fallback_sql += " AND source_path = ?"
                fallback_params.append(str(source_path))
            fallback_sql += " ORDER BY id ASC LIMIT ?"
            fallback_params.append(max(1, min(int(limit or 6), 20)))
            return [dict(row) for row in connection.execute(fallback_sql, fallback_params).fetchall()]
        finally:
            connection.close()
