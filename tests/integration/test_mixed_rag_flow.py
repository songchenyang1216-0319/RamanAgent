from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

import backend.db.database as database
from backend.services.rag import EmbeddingService, RAGService, VectorStore
from backend.services.rag.retriever import RAGRetriever


def _insert_rows(user_id: str, conversation_id: str, file_id: str, kb_id: str, kb_file_id: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = database.get_db_connection(database.DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO file_chunks (chunk_id, user_id, conversation_id, file_id, filename, source_path, section, text, token_estimate, metadata_json, created_at, source_type, chunk_index, text_hash, updated_at, rag_indexed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"chunk_{uuid4().hex}", user_id, conversation_id, file_id, "conversation_fact.md", "conversation_fact.md", "事实 A", "会话文件事实 A：样品 A 的采集温度是 25 摄氏度。", 32, "{}", now, "markdown", 0, uuid4().hex, now, 0),
        )
        conn.execute(
            """
            INSERT INTO knowledge_bases (knowledge_base_id, owner_user_id, name, description, visibility, enabled, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (kb_id, user_id, "Demo KB", "mixed rag", "private", 1, now, now, None),
        )
        conn.execute(
            """
            INSERT INTO conversation_knowledge_bases (conversation_id, user_id, knowledge_base_id, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, user_id, kb_id, 1, now, now),
        )
        conn.execute(
            """
            INSERT INTO knowledge_base_chunks (chunk_id, knowledge_base_id, kb_file_id, owner_user_id, source_name, source_type, text, page, sheet, section, chunk_index, text_hash, rag_indexed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"kb_chunk_{uuid4().hex}", kb_id, kb_file_id, user_id, "kb_fact.md", "markdown", "知识库事实 B：样品 B 的标准浓度是 12.5%。", 1, "", "事实 B", 0, uuid4().hex, 0, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def test_mixed_rag_flow_returns_both_sources_and_stats(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "mixed.sqlite")
    monkeypatch.setenv("RAG_ENABLE_RERANK", "true")
    database.init_agent_memory_db(database.DB_PATH)
    user_id = f"user_{uuid4().hex}"
    conversation_id = f"conv_{uuid4().hex}"
    file_id = f"file_{uuid4().hex}"
    kb_id = f"kb_{uuid4().hex}"
    kb_file_id = f"kb_file_{uuid4().hex}"
    _insert_rows(user_id, conversation_id, file_id, kb_id, kb_file_id)

    embedding = EmbeddingService(provider="mock")
    vector = VectorStore(provider="mock", persist_dir=tmp_path / "vectors")
    retriever = RAGRetriever(embedding_service=embedding, vector_store=vector, score_threshold=0.0)
    service = RAGService(embedding_service=embedding, vector_store=vector, retriever=retriever)
    assert service.index_file(file_id, user_id, conversation_id).success is True
    kb_chunks = service.retriever._keyword_knowledge_base("样品 B 标准浓度", knowledge_base_ids=[kb_id], top_k=1)
    assert service.index_knowledge_base_chunks(kb_chunks, owner_user_id=user_id, knowledge_base_id=kb_id, kb_file_id=kb_file_id).success is True

    result = service.search("样品 A 的采集温度和样品 B 的标准浓度分别是什么？", user_id, conversation_id, rag_scope="mixed", knowledge_base_ids=[])
    source_types = {item["source_type"] for item in result.citations}
    assert "conversation_file" in source_types
    assert "knowledge_base" in source_types
    assert result.source_breakdown["conversation_file_count"] >= 1
    assert result.source_breakdown["knowledge_base_count"] >= 1
    assert result.source_breakdown["candidate_count"] >= result.source_breakdown["rerank_output_count"] >= 1
    assert result.rerank["source_balance"] is True
    assert result.latency_ms >= 0
