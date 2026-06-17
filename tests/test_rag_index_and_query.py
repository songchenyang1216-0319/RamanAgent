from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.db.database import get_db_connection, init_agent_memory_db
from backend.services.llm_service import LLMService
from backend.services.rag import EmbeddingService, RAGService, VectorStore
from backend.services.rag.retriever import RAGRetriever


def _service(tmp_path: Path, *, score_threshold: float = 0.0) -> RAGService:
    embedding = EmbeddingService(provider="mock", model="mock-hash-embedding")
    vector = VectorStore(provider="mock", persist_dir=tmp_path / uuid4().hex)
    retriever = RAGRetriever(embedding_service=embedding, vector_store=vector, score_threshold=score_threshold)
    return RAGService(embedding_service=embedding, vector_store=vector, retriever=retriever)


def _insert_file_chunk(*, user_id: str, conversation_id: str, file_id: str, filename: str, text: str) -> str:
    init_agent_memory_db()
    chunk_id = f"chunk_{uuid4().hex}"
    now = datetime.now().isoformat(timespec="seconds")
    connection = get_db_connection()
    try:
        connection.execute(
            """
            INSERT INTO file_chunks (
                chunk_id, user_id, conversation_id, file_id, filename, source_path,
                page, section, text, token_estimate, metadata_json, created_at,
                source_type, sheet, chunk_index, text_hash, updated_at, rag_indexed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                user_id,
                conversation_id,
                file_id,
                filename,
                filename,
                "1",
                "实验背景",
                text,
                len(text),
                "{}",
                now,
                "file",
                "",
                0,
                uuid4().hex,
                now,
                0,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return chunk_id


def test_file_chunk_can_be_indexed_and_queried(tmp_path: Path) -> None:
    user_id = f"user_{uuid4().hex}"
    conversation_id = f"conv_{uuid4().hex}"
    file_id = f"file_{uuid4().hex}"
    chunk_id = _insert_file_chunk(
        user_id=user_id,
        conversation_id=conversation_id,
        file_id=file_id,
        filename="methanol_note.md",
        text="甲醇 Raman 光谱在 1030 cm-1 附近有明显特征峰，可用于浓度分析。",
    )
    service = _service(tmp_path)

    index_result = service.index_file(file_id, user_id, conversation_id)
    assert index_result.success is True
    assert index_result.chunk_count == 1

    search = service.search("甲醇 特征峰 1030", user_id, conversation_id, file_ids=[file_id])
    assert search.success is True
    assert search.chunks[0].chunk_id == chunk_id
    assert search.citations[0]["file_name"] == "methanol_note.md"


def test_answer_with_rag_returns_citations(monkeypatch, tmp_path: Path) -> None:
    user_id = f"user_{uuid4().hex}"
    conversation_id = f"conv_{uuid4().hex}"
    file_id = f"file_{uuid4().hex}"
    _insert_file_chunk(
        user_id=user_id,
        conversation_id=conversation_id,
        file_id=file_id,
        filename="qa.md",
        text="实验报告说明：SG 平滑用于降低 Raman 光谱高频噪声。",
    )
    service = _service(tmp_path)
    service.index_file(file_id, user_id, conversation_id)
    monkeypatch.setattr(
        LLMService,
        "generate_general_reply",
        lambda self, message, system_context=None: {"reply": "SG 平滑用于降低高频噪声。", "model_info": {"provider": "mock"}},
    )

    answer = service.answer_with_rag("SG 平滑有什么作用？", user_id, conversation_id, file_ids=[file_id])
    payload = answer.to_dict()
    assert payload["success"] is True
    assert payload["citations"]
    assert payload["retrieved_chunks"]
    assert payload["retrieval_mode"] in {"vector", "keyword_fallback"}

