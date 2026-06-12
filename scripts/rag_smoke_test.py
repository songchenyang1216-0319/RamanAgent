from __future__ import annotations

import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("VECTOR_DB_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("RAG_ENABLE_RERANK", "true")

from backend.services.rag import EmbeddingService, RAGService, RAGRetriever, VectorStore  # noqa: E402
from backend.services.rag.schemas import RetrievedChunk  # noqa: E402


def main() -> int:
    embedding = EmbeddingService()
    vector = VectorStore(provider="mock", persist_dir=PROJECT_ROOT / "storage" / "tmp" / "rag_smoke_vectors")
    retriever = RAGRetriever(embedding_service=embedding, vector_store=vector)
    chunks = [
        RetrievedChunk(chunk_id="conv-1", file_id="f1", conversation_id="conv", user_id="u", filename="a.txt", text="当前会话文件包含甲醇 Raman 光谱。", rag_scope="conversation", score=0.5),
        RetrievedChunk(chunk_id="kb-1", file_id=None, conversation_id=None, user_id="u", filename="kb.md", text="知识库说明甲醇检测流程和报告结构。", rag_scope="knowledge_base", score=0.4, knowledge_base_id="kb1"),
    ]
    reranked = retriever.reranker.rerank("甲醇检测报告", chunks, top_k=2, enforce_source_balance=True)
    health = RAGService(embedding_service=embedding, vector_store=vector, retriever=retriever).health(user_id="default_user")
    assert embedding.embed_query("hello")
    assert len(reranked.chunks) == 2
    assert health["success"] is True
    print("RAG smoke test passed.")
    print(f"embedding={health['embedding']['embedding_provider']} vector={health['vector_store']['vector_provider']} rerank={reranked.info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
