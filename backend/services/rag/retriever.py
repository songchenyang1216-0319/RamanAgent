from __future__ import annotations

import json
import os
from typing import Any

from backend.db.database import get_db_connection, init_agent_memory_db
from backend.services.file_processor import FileProcessorRegistry

from .embedding_service import EmbeddingService
from .reranker import RAGReranker
from .schemas import RetrievedChunk
from .vector_store import VectorStore


class RAGRetriever:
    def __init__(
        self,
        *,
        embedding_service: EmbeddingService | None = None,
        vector_store: VectorStore | None = None,
        score_threshold: float | None = None,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or VectorStore()
        self.score_threshold = float(score_threshold if score_threshold is not None else os.getenv("RAG_SCORE_THRESHOLD", "0.25"))
        self.keyword_fallback = str(os.getenv("RAG_ENABLE_KEYWORD_FALLBACK", "true")).lower() != "false"
        self.file_registry = FileProcessorRegistry()
        self.reranker = RAGReranker()
        self.last_retrieval_mode = "none"
        self.last_rerank_info: dict[str, Any] = {}

    def retrieve_conversation(
        self,
        query: str,
        *,
        user_id: str,
        conversation_id: str,
        file_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        top_k = self._top_k(top_k)
        chunks: list[RetrievedChunk] = []
        if self.vector_store.is_available():
            query_embedding = self.embedding_service.embed_query(query)
            chunks = self.vector_store.search_conversation(query_embedding, user_id=user_id, conversation_id=conversation_id, file_ids=file_ids, top_k=top_k)
            chunks = self._filter_scores(chunks)
            self.last_retrieval_mode = "vector"
        if not chunks and self.keyword_fallback:
            chunks = self._keyword_conversation(query, user_id=user_id, conversation_id=conversation_id, file_ids=file_ids, top_k=top_k)
            self.last_retrieval_mode = "keyword_fallback" if chunks else "none"
        chunks = self._dedupe(chunks)
        reranked = self.reranker.rerank(query, chunks, top_k=top_k)
        self.last_rerank_info = reranked.info
        return reranked.chunks

    def retrieve_knowledge_base(
        self,
        query: str,
        *,
        user_id: str,
        knowledge_base_ids: list[str],
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        top_k = self._top_k(top_k)
        if not knowledge_base_ids:
            self.last_retrieval_mode = "none"
            return []
        chunks: list[RetrievedChunk] = []
        if self.vector_store.is_available():
            query_embedding = self.embedding_service.embed_query(query)
            chunks = self.vector_store.search_knowledge_base(query_embedding, knowledge_base_ids=knowledge_base_ids, top_k=top_k)
            chunks = self._filter_scores(chunks)
            self.last_retrieval_mode = "vector"
        if not chunks and self.keyword_fallback:
            chunks = self._keyword_knowledge_base(query, knowledge_base_ids=knowledge_base_ids, top_k=top_k)
            self.last_retrieval_mode = "keyword_fallback" if chunks else "none"
        chunks = self._dedupe(chunks)
        reranked = self.reranker.rerank(query, chunks, top_k=top_k)
        self.last_rerank_info = reranked.info
        return reranked.chunks

    def retrieve_mixed(
        self,
        query: str,
        *,
        user_id: str,
        conversation_id: str,
        file_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        top_k = self._top_k(top_k)
        candidate_k = min(20, max(top_k * 2, top_k + 4))
        conv = self.retrieve_conversation(query, user_id=user_id, conversation_id=conversation_id, file_ids=file_ids, top_k=max(1, candidate_k // 2))
        conv_mode = self.last_retrieval_mode
        kb = self.retrieve_knowledge_base(query, user_id=user_id, knowledge_base_ids=knowledge_base_ids or [], top_k=max(1, candidate_k // 2))
        kb_mode = self.last_retrieval_mode
        self.last_retrieval_mode = "vector" if "vector" in {conv_mode, kb_mode} else ("keyword_fallback" if conv or kb else "none")
        chunks = self._dedupe(conv + kb)
        reranked = self.reranker.rerank(query, chunks, top_k=top_k, enforce_source_balance=True)
        self.last_rerank_info = {
            **reranked.info,
            "conversation_candidates": len(conv),
            "knowledge_base_candidates": len(kb),
            "source_balance": True,
        }
        return reranked.chunks

    def _keyword_conversation(self, query: str, *, user_id: str, conversation_id: str, file_ids: list[str] | None, top_k: int) -> list[RetrievedChunk]:
        rows = self.file_registry.search_chunks(user_id=user_id, conversation_id=conversation_id, query=query, file_ids=file_ids, limit=top_k)
        return [self._row_to_retrieved(row, rag_scope="conversation") for row in rows]

    def _keyword_knowledge_base(self, query: str, *, knowledge_base_ids: list[str], top_k: int) -> list[RetrievedChunk]:
        init_agent_memory_db()
        tokens = [token for token in str(query or "").lower().split() if token]
        like_terms = [f"%{token}%" for token in tokens[:5]]
        connection = get_db_connection()
        try:
            placeholders = ",".join("?" for _ in knowledge_base_ids)
            sql = f"SELECT * FROM knowledge_base_chunks WHERE knowledge_base_id IN ({placeholders})"
            params: list[Any] = list(knowledge_base_ids)
            if like_terms:
                sql += " AND (" + " OR ".join("LOWER(text) LIKE ?" for _ in like_terms) + ")"
                params.extend(like_terms)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(top_k)
            rows = connection.execute(sql, params).fetchall()
            if not rows and like_terms:
                rows = connection.execute(f"SELECT * FROM knowledge_base_chunks WHERE knowledge_base_id IN ({placeholders}) ORDER BY id ASC LIMIT ?", [*knowledge_base_ids, top_k]).fetchall()
            return [self._row_to_retrieved(dict(row), rag_scope="knowledge_base") for row in rows]
        finally:
            connection.close()

    def _row_to_retrieved(self, row: dict[str, Any], *, rag_scope: str) -> RetrievedChunk:
        metadata = {}
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except Exception:
            metadata = {}
        if rag_scope == "knowledge_base":
            return RetrievedChunk(
                chunk_id=str(row.get("chunk_id")),
                file_id=None,
                conversation_id=None,
                user_id=str(row.get("owner_user_id") or ""),
                filename=str(row.get("source_name") or ""),
                source_type=str(row.get("source_type") or "knowledge_base"),
                text=str(row.get("text") or ""),
                page=row.get("page"),
                sheet=row.get("sheet"),
                section=row.get("section"),
                chunk_index=int(row.get("chunk_index") or 0),
                metadata=metadata,
                rag_scope="knowledge_base",
                knowledge_base_id=str(row.get("knowledge_base_id") or ""),
                kb_file_id=str(row.get("kb_file_id") or ""),
                source_group="knowledge_base",
                score=None,
                distance=None,
                retrieval_mode="keyword_fallback",
            )
        return RetrievedChunk(
            chunk_id=str(row.get("chunk_id")),
            file_id=str(row.get("file_id") or ""),
            conversation_id=str(row.get("conversation_id") or ""),
            user_id=str(row.get("user_id") or ""),
            filename=str(row.get("filename") or ""),
            source_type=str(row.get("source_type") or "file"),
            text=str(row.get("text") or ""),
            page=row.get("page"),
            sheet=row.get("sheet"),
            section=row.get("section"),
            chunk_index=int(row.get("chunk_index") or 0),
            metadata=metadata,
            rag_scope="conversation",
            source_group="conversation_file",
            score=None,
            distance=None,
            retrieval_mode="keyword_fallback",
        )

    def _filter_scores(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return [chunk for chunk in chunks if chunk.score is None or chunk.score >= self.score_threshold]

    def _dedupe(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        seen = set()
        result = []
        for chunk in chunks:
            if chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            result.append(chunk)
        return result

    def _top_k(self, value: int | None) -> int:
        return max(1, min(int(value or os.getenv("RAG_TOP_K", "6")), 20))
