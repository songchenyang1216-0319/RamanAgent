from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.db.database import get_db_connection, init_agent_memory_db
from backend.repositories.rag_query_repository import RagQueryRepository
from backend.services.llm_service import LLMService

from .chunker import RAGChunker
from .embedding_service import EmbeddingService
from .prompt import build_rag_context
from .retriever import RAGRetriever
from .schemas import DocumentChunk, IndexResult, RAGAnswer, RAGSearchResult, RetrievedChunk
from .vector_store import VectorStore


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RAGService:
    def __init__(
        self,
        *,
        embedding_service: EmbeddingService | None = None,
        vector_store: VectorStore | None = None,
        retriever: RAGRetriever | None = None,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or VectorStore()
        self.retriever = retriever or RAGRetriever(embedding_service=self.embedding_service, vector_store=self.vector_store)
        self.chunker = RAGChunker(
            chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "800")),
            chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "120")),
        )

    def enabled(self) -> bool:
        return str(os.getenv("RAG_ENABLED", "true")).lower() != "false"

    def index_file(self, file_id: str, user_id: str, conversation_id: str) -> IndexResult:
        if not self.enabled():
            return self._record_index(file_id=file_id, user_id=user_id, conversation_id=conversation_id, status="disabled", chunk_count=0, error_message="RAG_ENABLED=false")
        rows = self._load_file_chunk_rows(file_id=file_id, user_id=user_id, conversation_id=conversation_id)
        if not rows:
            return self._record_index(file_id=file_id, user_id=user_id, conversation_id=conversation_id, status="not_supported", chunk_count=0, error_message="没有可索引文本 chunk。")
        chunks = [
            DocumentChunk(
                chunk_id=str(row.get("chunk_id")),
                file_id=str(row.get("file_id") or file_id),
                conversation_id=conversation_id,
                user_id=user_id,
                filename=str(row.get("filename") or ""),
                source_type=str(row.get("source_type") or "file"),
                text=str(row.get("text") or ""),
                page=row.get("page"),
                sheet=row.get("sheet"),
                section=row.get("section"),
                chunk_index=int(row.get("chunk_index") or index),
                metadata=self._metadata(row),
                rag_scope="conversation",
                source_group="conversation_file",
            )
            for index, row in enumerate(rows)
            if str(row.get("text") or "").strip()
        ]
        return self._index_chunks(chunks, file_id=file_id, user_id=user_id, conversation_id=conversation_id, rag_scope="conversation")

    def index_files(self, file_ids: list[str], user_id: str, conversation_id: str) -> list[IndexResult]:
        return [self.index_file(file_id, user_id, conversation_id) for file_id in file_ids]

    def rebuild_conversation_index(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT DISTINCT file_id FROM file_chunks WHERE user_id = ? AND conversation_id = ? AND file_id IS NOT NULL",
                (user_id, conversation_id),
            ).fetchall()
        finally:
            connection.close()
        results = self.index_files([str(row["file_id"]) for row in rows], user_id, conversation_id)
        return {"success": True, "results": [result.to_dict() for result in results], "total": len(results)}

    def rebuild_all_indexes(self, user_id: str) -> dict[str, Any]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            conversation_rows = connection.execute(
                "SELECT DISTINCT conversation_id FROM file_chunks WHERE user_id = ? AND conversation_id IS NOT NULL AND conversation_id != ''",
                (user_id,),
            ).fetchall()
            kb_rows = connection.execute(
                """
                SELECT kb.knowledge_base_id, kb.owner_user_id, kb.name
                FROM knowledge_bases kb
                WHERE kb.deleted_at IS NULL AND kb.owner_user_id = ?
                ORDER BY kb.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        finally:
            connection.close()

        conversation_results = [self.rebuild_conversation_index(user_id, str(row["conversation_id"])) for row in conversation_rows]
        knowledge_base_results = []
        try:
            from backend.services.knowledge_base import KnowledgeBaseIndexer

            indexer = KnowledgeBaseIndexer()
            for row in kb_rows:
                knowledge_base_results.append(
                    indexer.rebuild_knowledge_base_index(
                        owner_user_id=str(row["owner_user_id"]),
                        knowledge_base_id=str(row["knowledge_base_id"]),
                        knowledge_base_name=str(row["name"] or ""),
                    )
                )
        except Exception as exc:
            knowledge_base_results.append({"success": False, "error_message": str(exc), "results": [], "total": 0})
        return {
            "success": True,
            "conversation_results": conversation_results,
            "knowledge_base_results": knowledge_base_results,
            "conversation_total": len(conversation_results),
            "knowledge_base_total": len(knowledge_base_results),
        }

    def health(self, *, user_id: str, conversation_id: str | None = None) -> dict[str, Any]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            conversation_chunks = connection.execute(
                """
                SELECT COUNT(*) AS count, SUM(CASE WHEN rag_indexed = 1 THEN 1 ELSE 0 END) AS indexed_count
                FROM file_chunks
                WHERE user_id = ? AND (? = '' OR conversation_id = ?)
                """,
                (user_id, conversation_id or "", conversation_id or ""),
            ).fetchone()
            knowledge_chunks = connection.execute(
                """
                SELECT COUNT(*) AS count, SUM(CASE WHEN rag_indexed = 1 THEN 1 ELSE 0 END) AS indexed_count
                FROM knowledge_base_chunks
                WHERE owner_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            failed_indexes = connection.execute(
                """
                SELECT rag_scope, file_id, knowledge_base_id, kb_file_id, error_message, updated_at
                FROM rag_indexes
                WHERE user_id = ? AND status = 'failed'
                ORDER BY id DESC
                LIMIT 10
                """,
                (user_id,),
            ).fetchall()
        finally:
            connection.close()

        embedding = self.embedding_service.get_model_info()
        vector_store = self.vector_store.get_stats()
        app_env = str(os.getenv("APP_ENV", "development") or "development").lower()
        warnings: list[str] = []
        if app_env == "production" and embedding.get("embedding_provider") == "mock":
            warnings.append("生产环境正在使用 mock embedding，建议切换为 local 或 remote。")
        if self.enabled() and not vector_store.get("available"):
            warnings.append(vector_store.get("error_message") or "向量库不可用。")
        if not self.enabled():
            warnings.append("RAG_ENABLED=false，检索增强能力当前关闭。")

        def _counts(row: Any) -> dict[str, int]:
            count = int(row["count"] or 0) if row else 0
            indexed = int(row["indexed_count"] or 0) if row else 0
            return {
                "chunk_count": count,
                "indexed_chunk_count": indexed,
                "needs_reindex_count": max(0, count - indexed),
            }

        return {
            "success": True,
            "rag_enabled": self.enabled(),
            "app_env": app_env,
            "embedding": embedding,
            "vector_store": vector_store,
            "conversation_id": conversation_id,
            "conversation": _counts(conversation_chunks),
            "knowledge_base": _counts(knowledge_chunks),
            "failed_indexes": [dict(row) for row in failed_indexes],
            "production_warnings": warnings,
        }

    def index_knowledge_base_chunks(
        self,
        chunks: list[DocumentChunk],
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        kb_file_id: str,
    ) -> IndexResult:
        return self._index_chunks(
            chunks,
            file_id=None,
            user_id=owner_user_id,
            conversation_id="",
            rag_scope="knowledge_base",
            knowledge_base_id=knowledge_base_id,
            kb_file_id=kb_file_id,
        )

    def search(
        self,
        query: str,
        user_id: str,
        conversation_id: str,
        *,
        file_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        top_k: int | None = None,
        rag_scope: str = "conversation",
    ) -> RAGSearchResult:
        rag_scope = rag_scope if rag_scope in {"conversation", "knowledge_base", "mixed"} else "conversation"
        if rag_scope == "knowledge_base":
            chunks = self.retriever.retrieve_knowledge_base(query, user_id=user_id, knowledge_base_ids=knowledge_base_ids or [], top_k=top_k)
        elif rag_scope == "mixed":
            chunks = self.retriever.retrieve_mixed(query, user_id=user_id, conversation_id=conversation_id, file_ids=file_ids, knowledge_base_ids=knowledge_base_ids, top_k=top_k)
        else:
            chunks = self.retriever.retrieve_conversation(query, user_id=user_id, conversation_id=conversation_id, file_ids=file_ids, top_k=top_k)
        citations = self._citations(chunks)
        result = RAGSearchResult(
            success=bool(chunks),
            query=query,
            rag_scope=rag_scope,
            chunks=chunks,
            conversation_chunks=[chunk for chunk in chunks if chunk.rag_scope == "conversation"],
            knowledge_base_chunks=[chunk for chunk in chunks if chunk.rag_scope == "knowledge_base"],
            retrieval_mode=self.retriever.last_retrieval_mode,
            rerank=dict(self.retriever.last_rerank_info or {}),
            citations=citations,
            source_breakdown=self._source_breakdown(chunks),
            error_message=None if chunks else "没有检索到足够相关的片段。",
        )
        self._record_query(user_id, conversation_id, query, file_ids, knowledge_base_ids, rag_scope, result)
        return result

    def answer_with_rag(
        self,
        query: str,
        user_id: str,
        conversation_id: str,
        *,
        file_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        rag_scope: str = "conversation",
    ) -> RAGAnswer:
        started = time.perf_counter()
        search_result = self.search(query, user_id, conversation_id, file_ids=file_ids, knowledge_base_ids=knowledge_base_ids, rag_scope=rag_scope)
        if not search_result.chunks:
            answer_text = "资料中未找到足够依据，建议先上传文件或启用相关知识库。"
            self._record_answer_query(
                user_id,
                conversation_id,
                query,
                file_ids,
                knowledge_base_ids,
                rag_scope,
                search_result,
                answer_text,
                int((time.perf_counter() - started) * 1000),
                {},
            )
            return RAGAnswer(False, query, answer_text, rag_scope, retrieval_mode=search_result.retrieval_mode, rerank=search_result.rerank, error_message=search_result.error_message)
        chunk_dicts = [chunk.to_dict() for chunk in search_result.chunks]
        context = build_rag_context(chunk_dicts, rag_scope=rag_scope)
        llm_result = LLMService(user_id=user_id, conversation_id=conversation_id).generate_general_reply(query, system_context=context)
        answer = str(llm_result.get("reply") or "").strip()
        if not answer:
            answer = self._fallback_answer(query, search_result.chunks)
        latency_ms = int((time.perf_counter() - started) * 1000)
        self._record_answer_query(
            user_id,
            conversation_id,
            query,
            file_ids,
            knowledge_base_ids,
            rag_scope,
            search_result,
            answer,
            latency_ms,
            dict(llm_result.get("model_info") or {}),
        )
        return RAGAnswer(
            success=True,
            query=query,
            answer=answer,
            rag_scope=rag_scope,
            citations=search_result.citations,
            retrieved_chunks=chunk_dicts,
            source_breakdown=search_result.source_breakdown,
            retrieval_mode=search_result.retrieval_mode,
            rerank=search_result.rerank,
            model_info=dict(llm_result.get("model_info") or {}),
            rag={
                "top_k": int(os.getenv("RAG_TOP_K", "6")),
                "score_threshold": float(os.getenv("RAG_SCORE_THRESHOLD", "0.25")),
                "rerank": search_result.rerank,
                **self.embedding_service.get_model_info(),
                "vector_provider": self.vector_store.provider,
            },
            error_message=None,
        )

    def answer_with_conversation_rag(self, query: str, user_id: str, conversation_id: str, file_ids: list[str] | None = None) -> RAGAnswer:
        return self.answer_with_rag(query, user_id, conversation_id, file_ids=file_ids, rag_scope="conversation")

    def answer_with_knowledge_base_rag(self, query: str, user_id: str, knowledge_base_ids: list[str]) -> RAGAnswer:
        return self.answer_with_rag(query, user_id, "", knowledge_base_ids=knowledge_base_ids, rag_scope="knowledge_base")

    def answer_with_mixed_rag(self, query: str, user_id: str, conversation_id: str, file_ids: list[str] | None, knowledge_base_ids: list[str]) -> RAGAnswer:
        return self.answer_with_rag(query, user_id, conversation_id, file_ids=file_ids, knowledge_base_ids=knowledge_base_ids, rag_scope="mixed")

    def _index_chunks(
        self,
        chunks: list[DocumentChunk],
        *,
        file_id: str | None,
        user_id: str,
        conversation_id: str,
        rag_scope: str,
        knowledge_base_id: str | None = None,
        kb_file_id: str | None = None,
    ) -> IndexResult:
        if not chunks:
            return self._record_index(file_id=file_id, user_id=user_id, conversation_id=conversation_id, rag_scope=rag_scope, knowledge_base_id=knowledge_base_id, kb_file_id=kb_file_id, status="not_supported", chunk_count=0, error_message="没有可索引文本。")
        if not self.vector_store.is_available():
            return self._record_index(file_id=file_id, user_id=user_id, conversation_id=conversation_id, rag_scope=rag_scope, knowledge_base_id=knowledge_base_id, kb_file_id=kb_file_id, status="disabled", chunk_count=len(chunks), error_message=self.vector_store.get_stats().get("error_message") or "向量库不可用。")
        try:
            embeddings = self.embedding_service.embed_texts([chunk.text for chunk in chunks])
            self.vector_store.add_chunks(chunks, embeddings)
            self._mark_chunks_indexed(chunks, rag_scope=rag_scope)
            return self._record_index(file_id=file_id, user_id=user_id, conversation_id=conversation_id, rag_scope=rag_scope, knowledge_base_id=knowledge_base_id, kb_file_id=kb_file_id, status="indexed", chunk_count=len(chunks))
        except Exception as exc:
            return self._record_index(file_id=file_id, user_id=user_id, conversation_id=conversation_id, rag_scope=rag_scope, knowledge_base_id=knowledge_base_id, kb_file_id=kb_file_id, status="failed", chunk_count=len(chunks), error_message=str(exc))

    def _load_file_chunk_rows(self, *, file_id: str, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM file_chunks WHERE user_id = ? AND conversation_id = ? AND file_id = ? ORDER BY id ASC",
                (user_id, conversation_id, file_id),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def _metadata(self, row: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(row.get("metadata_json") or "{}")
        except Exception:
            return {}

    def _record_index(
        self,
        *,
        file_id: str | None,
        user_id: str,
        conversation_id: str | None,
        status: str,
        chunk_count: int,
        error_message: str | None = None,
        rag_scope: str = "conversation",
        knowledge_base_id: str | None = None,
        kb_file_id: str | None = None,
    ) -> IndexResult:
        init_agent_memory_db()
        now = now_iso()
        model_info = self.embedding_service.get_model_info()
        connection = get_db_connection()
        try:
            connection.execute(
                """
                INSERT INTO rag_indexes (
                    file_id, user_id, conversation_id, vector_provider, embedding_provider,
                    embedding_model, chunk_count, status, error_message, created_at,
                    updated_at, rag_scope, knowledge_base_id, kb_file_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id or kb_file_id or "",
                    user_id,
                    conversation_id or "",
                    self.vector_store.provider,
                    model_info.get("embedding_provider"),
                    model_info.get("embedding_model"),
                    chunk_count,
                    status,
                    error_message,
                    now,
                    now,
                    rag_scope,
                    knowledge_base_id,
                    kb_file_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return IndexResult(status == "indexed", file_id, user_id, conversation_id, rag_scope, knowledge_base_id, kb_file_id, status, chunk_count, self.vector_store.provider, model_info.get("embedding_provider"), model_info.get("embedding_model"), error_message)

    def _mark_chunks_indexed(self, chunks: list[DocumentChunk], *, rag_scope: str) -> None:
        if not chunks:
            return
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            if rag_scope == "knowledge_base":
                for chunk in chunks:
                    connection.execute("UPDATE knowledge_base_chunks SET rag_indexed = 1, updated_at = ? WHERE chunk_id = ?", (now_iso(), chunk.chunk_id))
            else:
                for chunk in chunks:
                    connection.execute("UPDATE file_chunks SET rag_indexed = 1, updated_at = ? WHERE chunk_id = ?", (now_iso(), chunk.chunk_id))
            connection.commit()
        finally:
            connection.close()

    def _record_query(self, user_id: str, conversation_id: str, query: str, file_ids: list[str] | None, knowledge_base_ids: list[str] | None, rag_scope: str, result: RAGSearchResult) -> None:
        RagQueryRepository().record_query(
            {
                "rag_query_id": uuid4().hex,
                "query_id": uuid4().hex,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "query": query,
                "file_ids_json": file_ids or [],
                "top_k": int(os.getenv("RAG_TOP_K", "6")),
                "retrieval_mode": result.retrieval_mode,
                "retrieved_chunk_ids_json": [chunk.chunk_id for chunk in result.chunks],
                "retrieved_chunks_json": [chunk.to_dict() for chunk in result.chunks],
                "citations_json": result.citations,
                "created_at": now_iso(),
                "rag_scope": rag_scope,
                "knowledge_base_ids_json": knowledge_base_ids or [],
                "source_breakdown_json": result.source_breakdown,
            }
        )

    def _record_answer_query(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        file_ids: list[str] | None,
        knowledge_base_ids: list[str] | None,
        rag_scope: str,
        result: RAGSearchResult,
        answer: str,
        latency_ms: int,
        model_info: dict[str, Any],
    ) -> None:
        RagQueryRepository().record_query(
            {
                "rag_query_id": uuid4().hex,
                "query_id": uuid4().hex,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "query": query,
                "rag_scope": rag_scope,
                "file_ids_json": file_ids or [],
                "knowledge_base_ids_json": knowledge_base_ids or [],
                "retrieved_chunks_json": [chunk.to_dict() for chunk in result.chunks],
                "retrieved_chunk_ids_json": [chunk.chunk_id for chunk in result.chunks],
                "citations_json": result.citations,
                "answer": answer,
                "latency_ms": latency_ms,
                "model_info_json": model_info,
                "retrieval_mode": result.retrieval_mode,
                "source_breakdown_json": result.source_breakdown,
                "top_k": int(os.getenv("RAG_TOP_K", "6")),
            }
        )

    def _citations(self, chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
        return [
            {
                "chunk_id": chunk.chunk_id,
                "source_type": chunk.rag_scope or chunk.source_type,
                "source_id": chunk.knowledge_base_id or chunk.file_id or chunk.kb_file_id,
                "file_id": chunk.file_id,
                "kb_file_id": chunk.kb_file_id,
                "knowledge_base_id": chunk.knowledge_base_id,
                "knowledge_base_name": chunk.knowledge_base_name,
                "filename": chunk.filename,
                "file_name": chunk.filename,
                "source_group": chunk.source_group,
                "rag_scope": chunk.rag_scope,
                "page": chunk.page,
                "sheet": chunk.sheet,
                "section": chunk.section,
                "score": chunk.score,
                "distance": chunk.distance,
                "preview": chunk.text[:240],
                "content_excerpt": chunk.text[:500],
            }
            for chunk in chunks
        ]

    def _source_breakdown(self, chunks: list[RetrievedChunk]) -> dict[str, Any]:
        conversation_files = []
        knowledge_bases = []
        for chunk in chunks:
            if chunk.rag_scope == "knowledge_base":
                knowledge_bases.append({"knowledge_base_id": chunk.knowledge_base_id, "knowledge_base_name": chunk.knowledge_base_name, "kb_file_id": chunk.kb_file_id, "filename": chunk.filename})
            else:
                conversation_files.append({"file_id": chunk.file_id, "filename": chunk.filename})
        return {"conversation_files": conversation_files, "knowledge_bases": knowledge_bases}

    def _fallback_answer(self, query: str, chunks: list[RetrievedChunk]) -> str:
        lines = ["模型不可用，以下为基于检索片段的本地简要回答。", "", f"问题：{query}", "", "可用依据："]
        for chunk in chunks[:4]:
            lines.append(f"- {chunk.filename}: {chunk.text[:180]}")
        return "\n".join(lines)
