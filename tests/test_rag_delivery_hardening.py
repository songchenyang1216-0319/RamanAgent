from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.file_converter import FileConverterService
from backend.services.knowledge_base import KnowledgeBaseIndexer
from backend.services.ocr import OCRService
from backend.services.rag import EmbeddingService, RAGService, VectorStore
from backend.services.rag.reranker import RAGReranker
from backend.services.rag.schemas import RetrievedChunk
from scripts.check_env_safety import main as check_env_safety_main


def test_mixed_rag_reranker_balances_sources():
    chunks = [
        RetrievedChunk(chunk_id="c1", file_id="f1", conversation_id="conv", user_id="u", filename="file.txt", text="当前文件包含甲醇报告", rag_scope="conversation", score=0.9),
        RetrievedChunk(chunk_id="k1", file_id=None, conversation_id=None, user_id="u", filename="kb.md", text="知识库包含甲醇报告模板", rag_scope="knowledge_base", knowledge_base_id="kb1", score=0.2),
        RetrievedChunk(chunk_id="c2", file_id="f2", conversation_id="conv", user_id="u", filename="file2.txt", text="当前文件其他内容", rag_scope="conversation", score=0.8),
    ]
    result = RAGReranker(enabled=True).rerank("甲醇报告", chunks, top_k=2, enforce_source_balance=True)
    scopes = {chunk.rag_scope for chunk in result.chunks}
    assert result.info["applied"] is True
    assert scopes == {"conversation", "knowledge_base"}


def test_embedding_model_info_warns_for_mock_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    info = EmbeddingService().get_model_info()
    assert info["embedding_is_mock"] is True
    assert info["production_ready"] is False
    assert info["warnings"]


def test_rag_health_reports_production_warning(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "production")
    service = RAGService(
        embedding_service=EmbeddingService(provider="mock"),
        vector_store=VectorStore(provider="mock", persist_dir=tmp_path / "vectors"),
    )
    health = service.health(user_id="default_user", conversation_id="unit-health")
    assert health["success"] is True
    assert health["production_warnings"]


def test_pdf_export_falls_back_to_html_when_provider_disabled(monkeypatch):
    monkeypatch.setenv("PDF_EXPORT_PROVIDER", "none")
    content, actual_format, available, warnings = FileConverterService()._text_to_pdf_or_fallback("hello", "note.txt")
    assert actual_format == "html"
    assert available is False
    assert "hello" in content
    assert warnings


def test_ocr_provider_can_be_disabled(monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "none")
    status = OCRService().get_status()
    assert status["available"] is False
    assert status["provider"] == "none"


def test_knowledge_base_index_status_empty_is_explicit():
    status = KnowledgeBaseIndexer().get_knowledge_base_index_status(owner_user_id="unit-user", knowledge_base_id="kb_empty_unit")
    assert status["success"] is True
    assert status["status"] == "empty"
    assert status["chunk_count"] == 0


def test_env_safety_script_passes_for_example_file():
    assert check_env_safety_main() == 0
