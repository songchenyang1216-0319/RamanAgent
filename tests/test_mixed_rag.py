from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.db.database import get_db_connection, init_agent_memory_db
from backend.services.rag import EmbeddingService, RAGService, VectorStore
from backend.services.rag.retriever import RAGRetriever


def _insert_mixed_rows(user_id: str, conversation_id: str, file_id: str, kb_id: str, kb_file_id: str) -> None:
    init_agent_memory_db()
    now = datetime.now().isoformat(timespec="seconds")
    connection = get_db_connection()
    try:
        connection.execute(
            """
            INSERT INTO file_chunks (
                chunk_id, user_id, conversation_id, file_id, filename, source_path,
                text, token_estimate, metadata_json, created_at, source_type,
                chunk_index, updated_at, rag_indexed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"chunk_{uuid4().hex}",
                user_id,
                conversation_id,
                file_id,
                "conversation.md",
                "conversation.md",
                "当前会话文件说明 Raman 样品 A 需要做 SG 平滑。",
                40,
                "{}",
                now,
                "file",
                0,
                now,
                0,
            ),
        )
        connection.execute(
            """
            INSERT INTO knowledge_bases (
                knowledge_base_id, owner_user_id, name, description, visibility,
                enabled, created_at, updated_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (kb_id, user_id, "Raman KB", "demo", "private", 1, now, now, None),
        )
        connection.execute(
            """
            INSERT INTO conversation_knowledge_bases (
                conversation_id, user_id, knowledge_base_id, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, user_id, kb_id, 1, now, now),
        )
        connection.execute(
            """
            INSERT INTO knowledge_base_chunks (
                chunk_id, knowledge_base_id, kb_file_id, owner_user_id, source_name,
                source_type, text, page, sheet, section, chunk_index, text_hash,
                rag_indexed, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"kb_chunk_{uuid4().hex}",
                kb_id,
                kb_file_id,
                user_id,
                "kb.md",
                "knowledge_base",
                "知识库资料说明 ALS 去基线可修正 Raman 背景漂移。",
                1,
                "",
                "预处理",
                0,
                uuid4().hex,
                0,
                now,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_mixed_rag_returns_conversation_and_knowledge_base_sources(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RAG_ENABLE_RERANK", "true")
    user_id = f"user_{uuid4().hex}"
    conversation_id = f"conv_{uuid4().hex}"
    file_id = f"file_{uuid4().hex}"
    kb_id = f"kb_{uuid4().hex}"
    kb_file_id = f"kb_file_{uuid4().hex}"
    _insert_mixed_rows(user_id, conversation_id, file_id, kb_id, kb_file_id)
    embedding = EmbeddingService(provider="mock")
    vector = VectorStore(provider="mock", persist_dir=tmp_path / "vectors")
    retriever = RAGRetriever(embedding_service=embedding, vector_store=vector, score_threshold=0.0)
    service = RAGService(embedding_service=embedding, vector_store=vector, retriever=retriever)
    service.index_file(file_id, user_id, conversation_id)
    kb_chunks = service.retriever._keyword_knowledge_base("ALS Raman", knowledge_base_ids=[kb_id], top_k=1)
    service.index_knowledge_base_chunks(kb_chunks, owner_user_id=user_id, knowledge_base_id=kb_id, kb_file_id=kb_file_id)

    result = service.search("Raman 预处理 SG ALS", user_id, conversation_id, rag_scope="mixed", knowledge_base_ids=[])
    scopes = {chunk.rag_scope for chunk in result.chunks}
    assert {"conversation", "knowledge_base"}.issubset(scopes)
    assert result.source_breakdown["conversation_file_count"] >= 1
    assert result.source_breakdown["knowledge_base_count"] >= 1
    assert result.rerank["source_balance"] is True

