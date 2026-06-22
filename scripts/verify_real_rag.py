from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _require_package(module_name: str, install_name: str) -> None:
    if importlib.util.find_spec(module_name) is None:
        raise RuntimeError(f"缺少依赖 {install_name}，请先执行 pip install -r requirements.txt。")


def _configure_real_rag() -> None:
    os.environ["VECTOR_DB_PROVIDER"] = "chroma"
    os.environ["VECTOR_DB_DIR"] = os.getenv("VECTOR_DB_DIR", "storage/vector_db")
    os.environ["VECTOR_DB_COLLECTION"] = os.getenv("VECTOR_DB_COLLECTION", "ramanagent_real_rag_verify")
    os.environ["EMBEDDING_PROVIDER"] = "local"
    os.environ["EMBEDDING_MODEL"] = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    os.environ["RAG_TOP_K"] = os.getenv("RAG_TOP_K", "6")
    os.environ["RAG_SCORE_THRESHOLD"] = os.getenv("RAG_SCORE_THRESHOLD", "0.25")
    os.environ["RAG_ENABLE_KEYWORD_FALLBACK"] = os.getenv("RAG_ENABLE_KEYWORD_FALLBACK", "true")
    os.environ["RAG_ENABLE_RERANK"] = os.getenv("RAG_ENABLE_RERANK", "true")
    os.environ["RAG_RERANK_PROVIDER"] = os.getenv("RAG_RERANK_PROVIDER", "lexical")


def main() -> int:
    _configure_real_rag()
    _require_package("chromadb", "chromadb")
    _require_package("sentence_transformers", "sentence-transformers")

    from backend.services.rag.embedding_service import EmbeddingService
    from backend.services.rag.retriever import RAGRetriever
    from backend.services.rag.schemas import DocumentChunk
    from backend.services.rag.vector_store import VectorStore

    embedding = EmbeddingService()
    vector_store = VectorStore()
    retriever = RAGRetriever(embedding_service=embedding, vector_store=vector_store)

    model_info = embedding.get_model_info()
    if model_info["embedding_provider"] != "local" or model_info["embedding_is_mock"]:
        raise RuntimeError(f"真实 RAG 验证拒绝使用 mock embedding：{model_info}")
    if vector_store.provider != "chroma":
        raise RuntimeError(f"真实 RAG 验证拒绝使用非 Chroma 向量库：{vector_store.provider}")

    user_id = f"real_rag_user_{uuid4().hex[:8]}"
    conversation_id = f"real_rag_conv_{uuid4().hex[:8]}"
    file_id = f"real_rag_file_{uuid4().hex[:8]}"
    chunks = [
        DocumentChunk(
            chunk_id=f"{file_id}_0",
            file_id=file_id,
            conversation_id=conversation_id,
            user_id=user_id,
            filename="real_rag_manual.md",
            source_type="file",
            text="RamanAgent 真实 Chroma local embedding 验证文本。项目内部演示代号是 RA-REAL-RAG-2026。",
            chunk_index=0,
            rag_scope="conversation",
            source_group="conversation_file",
        ),
        DocumentChunk(
            chunk_id=f"{file_id}_1",
            file_id=file_id,
            conversation_id=conversation_id,
            user_id=user_id,
            filename="real_rag_manual.md",
            source_type="file",
            text="RAG 使用 BAAI/bge-small-zh-v1.5 本地模型生成向量，并写入 Chroma 持久化目录。",
            chunk_index=1,
            rag_scope="conversation",
            source_group="conversation_file",
        ),
    ]

    try:
        embeddings = embedding.embed_texts([chunk.text for chunk in chunks])
    except Exception as exc:
        raise RuntimeError(f"本地 embedding 模型加载或编码失败：{exc}") from exc

    if not embeddings or not embeddings[0]:
        raise RuntimeError("本地 embedding 返回空向量。")

    vector_store.add_chunks(chunks, embeddings)
    results = retriever.retrieve_conversation(
        "RamanAgent 真实 RAG 演示代号是什么？",
        user_id=user_id,
        conversation_id=conversation_id,
        file_ids=[file_id],
        top_k=6,
    )
    if not results:
        raise RuntimeError("Chroma 检索没有返回结果，请检查 VECTOR_DB_DIR、模型向量维度和 score threshold。")
    if not any("RA-REAL-RAG-2026" in item.text for item in results):
        raise RuntimeError("Chroma 检索结果未命中验证文本，真实 RAG 链路未通过。")

    print("Real Chroma + local embedding verification passed.")
    print(f"vector_provider={vector_store.provider}")
    print(f"vector_dir={vector_store.persist_dir}")
    print(f"collection={vector_store.collection_name}")
    print(f"embedding_provider={model_info['embedding_provider']}")
    print(f"embedding_model={model_info['embedding_model']}")
    print(f"embedding_dim={len(embeddings[0])}")
    print(f"retrieval_mode={retriever.last_retrieval_mode}")
    print(f"rerank={retriever.last_rerank_info}")
    print(f"top_hit={results[0].filename} score={results[0].score} text={results[0].text[:120]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Real Chroma + local embedding verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
