from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

import backend.db.database as database
from backend.services.file_processor import FileProcessorRegistry
from backend.services.llm_service import LLMService
from backend.services.rag import EmbeddingService, RAGService, VectorStore
from backend.services.rag.retriever import RAGRetriever


def _isolated_rag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RAGService:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "rag_flow.sqlite")
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("RAG_ENABLE_RERANK", "true")
    database.init_agent_memory_db(database.DB_PATH)
    embedding = EmbeddingService(provider="mock", model="mock-hash-embedding")
    vector = VectorStore(provider="mock", persist_dir=tmp_path / "vectors")
    retriever = RAGRetriever(embedding_service=embedding, vector_store=vector, score_threshold=0.0)
    return RAGService(embedding_service=embedding, vector_store=vector, retriever=retriever)


def test_real_rag_flow_indexes_queries_cites_and_no_answers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = _isolated_rag(monkeypatch, tmp_path)
    user_id = f"user_{uuid4().hex}"
    conversation_id = f"conv_{uuid4().hex}"
    file_id = f"file_{uuid4().hex}"
    source = tmp_path / "ra_fact.md"
    source.write_text(
        "# RamanAgent 测试资料\n\n"
        "RamanAgent 测试项目的内部代号是 RA-2026-DEMO。\n"
        "项目默认演示数据包含 65 份甲醇光谱 CSV。\n",
        encoding="utf-8",
    )

    processed = FileProcessorRegistry().process(source, file_id=file_id, user_id=user_id, conversation_id=conversation_id)
    assert processed.success is True
    assert processed.chunks

    index = service.index_file(file_id, user_id, conversation_id)
    assert index.success is True
    assert index.chunk_count >= 1

    search = service.search("RamanAgent 的内部代号是什么？", user_id, conversation_id, file_ids=[file_id])
    assert search.success is True
    assert any("RA-2026-DEMO" in chunk.text for chunk in search.chunks)
    assert search.citations[0]["file_name"] == "ra_fact.md"
    assert search.citations[0]["source_type"] == "conversation_file"
    assert search.source_breakdown["candidate_count"] >= 1
    assert search.latency_ms >= 0

    monkeypatch.setattr(
        LLMService,
        "generate_general_reply",
        lambda self, message, system_context=None: {"reply": "内部代号是 RA-2026-DEMO。", "model_info": {"provider": "mock"}},
    )
    answer = service.answer_with_rag("RamanAgent 的内部代号是什么？", user_id, conversation_id, file_ids=[file_id])
    assert answer.success is True
    assert "RA-2026-DEMO" in answer.answer
    assert answer.citations and answer.citations[0]["file_name"] == "ra_fact.md"

    no_answer = service.answer_with_rag("资料里有没有火星采样计划？", user_id, conversation_id, file_ids=["missing_file"])
    assert no_answer.success is False
    assert "资料中未找到足够依据" in no_answer.answer
    assert no_answer.citations == []
    assert no_answer.rag["no_answer"] is True


def test_chroma_local_config_error_is_clear(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "chroma")
    monkeypatch.setenv("VECTOR_DB_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("EMBEDDING_MODEL", "definitely/missing-local-model")
    service = RAGService(vector_store=VectorStore(provider="chroma", persist_dir=tmp_path / "chroma"), embedding_service=EmbeddingService(provider="local", model="definitely/missing-local-model"))
    info = service.embedding_service.get_model_info()
    assert info["embedding_provider"] == "local"
    assert info["embedding_is_mock"] is False
    assert "warnings" in info
