from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.db.database import get_db_connection, init_agent_memory_db
from backend.services.rag import EmbeddingService, RAGService, VectorStore
from backend.services.rag.retriever import RAGRetriever


def _insert_chunk(user_id: str, conversation_id: str, file_id: str) -> None:
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
                "note.md",
                "note.md",
                "这是一段关于 Raman 甲醇校准的资料。",
                32,
                "{}",
                now,
                "file",
                0,
                now,
                0,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_answer_with_rag_no_context_does_not_fabricate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RAG_ENABLE_KEYWORD_FALLBACK", "false")
    user_id = f"user_{uuid4().hex}"
    conversation_id = f"conv_{uuid4().hex}"
    file_id = f"file_{uuid4().hex}"
    _insert_chunk(user_id, conversation_id, file_id)
    embedding = EmbeddingService(provider="mock")
    vector = VectorStore(provider="mock", persist_dir=tmp_path / "vectors")
    retriever = RAGRetriever(embedding_service=embedding, vector_store=vector, score_threshold=0.99)
    service = RAGService(embedding_service=embedding, vector_store=vector, retriever=retriever)
    service.index_file(file_id, user_id, conversation_id)

    answer = service.answer_with_rag("火星基地的预算是多少？", user_id, conversation_id, file_ids=[file_id])
    assert answer.success is False
    assert "资料中未找到足够依据" in answer.answer
    assert answer.citations == []


def test_local_embedding_missing_dependency_reports_clear_error(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    service = EmbeddingService(provider="local", model="BAAI/bge-small-zh-v1.5")
    try:
        service.embed_texts(["hello"])
    except RuntimeError as exc:
        assert "sentence-transformers" in str(exc)
    else:
        raise AssertionError("local embedding 缺少依赖时不应静默成功")

