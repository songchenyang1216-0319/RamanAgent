from __future__ import annotations

import hashlib
import re
from typing import Any

from .schemas import DocumentChunk


class RAGChunker:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120) -> None:
        self.chunk_size = max(200, int(chunk_size or 800))
        self.chunk_overlap = max(0, min(int(chunk_overlap or 0), self.chunk_size // 2))

    def from_file_processor_chunks(
        self,
        chunks: list[dict[str, Any]],
        *,
        user_id: str,
        conversation_id: str,
        file_id: str | None,
        filename: str,
        source_type: str,
        rag_scope: str = "conversation",
        knowledge_base_id: str | None = None,
        knowledge_base_name: str | None = None,
        kb_file_id: str | None = None,
    ) -> list[DocumentChunk]:
        results: list[DocumentChunk] = []
        for index, chunk in enumerate(chunks):
            text = str(chunk.get("text") or "").strip()
            if not text:
                continue
            metadata = dict(chunk.get("metadata") or {})
            results.append(
                DocumentChunk(
                    chunk_id=str(chunk.get("chunk_id") or self._chunk_id(filename, index, text)),
                    file_id=file_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    filename=filename,
                    source_type=source_type,
                    text=text,
                    page=chunk.get("page"),
                    sheet=chunk.get("sheet"),
                    section=chunk.get("section"),
                    chunk_index=int(chunk.get("chunk_index") or index),
                    metadata={**metadata, "text_hash": self._hash_text(text)},
                    rag_scope=rag_scope,
                    knowledge_base_id=knowledge_base_id,
                    knowledge_base_name=knowledge_base_name,
                    kb_file_id=kb_file_id,
                    source_group="knowledge_base" if rag_scope == "knowledge_base" else "conversation_file",
                )
            )
        return results

    def split_text(
        self,
        text: str,
        *,
        user_id: str,
        conversation_id: str = "",
        file_id: str | None = None,
        filename: str = "",
        source_type: str = "text",
        rag_scope: str = "conversation",
        knowledge_base_id: str | None = None,
        knowledge_base_name: str | None = None,
        kb_file_id: str | None = None,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[DocumentChunk]:
        normalized = str(text or "").replace("\r\n", "\n").strip()
        if not normalized:
            return []
        sections = self._paragraph_sections(normalized)
        chunks: list[DocumentChunk] = []
        buffer = ""
        section_name = ""
        for section, paragraph in sections:
            if len(buffer) + len(paragraph) + 2 > self.chunk_size and buffer:
                chunks.append(self._build_chunk(buffer, len(chunks), user_id, conversation_id, file_id, filename, source_type, rag_scope, knowledge_base_id, knowledge_base_name, kb_file_id, section_name, base_metadata))
                buffer = buffer[-self.chunk_overlap :] if self.chunk_overlap else ""
            section_name = section or section_name
            buffer = (buffer + "\n\n" + paragraph).strip()
        if buffer:
            chunks.append(self._build_chunk(buffer, len(chunks), user_id, conversation_id, file_id, filename, source_type, rag_scope, knowledge_base_id, knowledge_base_name, kb_file_id, section_name, base_metadata))
        return chunks

    def _paragraph_sections(self, text: str) -> list[tuple[str, str]]:
        current_heading = ""
        results: list[tuple[str, str]] = []
        for part in re.split(r"\n\s*\n+", text):
            paragraph = part.strip()
            if not paragraph:
                continue
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", paragraph.splitlines()[0])
            if heading_match:
                current_heading = heading_match.group(2).strip()
            results.append((current_heading, paragraph))
        return results

    def _build_chunk(
        self,
        text: str,
        index: int,
        user_id: str,
        conversation_id: str,
        file_id: str | None,
        filename: str,
        source_type: str,
        rag_scope: str,
        knowledge_base_id: str | None,
        knowledge_base_name: str | None,
        kb_file_id: str | None,
        section: str,
        base_metadata: dict[str, Any] | None,
    ) -> DocumentChunk:
        metadata = dict(base_metadata or {})
        metadata["text_hash"] = self._hash_text(text)
        return DocumentChunk(
            chunk_id=self._chunk_id(filename, index, text),
            file_id=file_id,
            conversation_id=conversation_id,
            user_id=user_id,
            filename=filename,
            source_type=source_type,
            text=text,
            section=section or None,
            chunk_index=index,
            metadata=metadata,
            rag_scope=rag_scope,
            knowledge_base_id=knowledge_base_id,
            knowledge_base_name=knowledge_base_name,
            kb_file_id=kb_file_id,
            source_group="knowledge_base" if rag_scope == "knowledge_base" else "conversation_file",
        )

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def _chunk_id(self, filename: str, index: int, text: str) -> str:
        digest = hashlib.sha1(f"{filename}:{index}:{text[:120]}".encode("utf-8", errors="ignore")).hexdigest()
        return digest
