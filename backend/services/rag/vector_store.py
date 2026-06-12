from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from raman_core.methanol.config import PROJECT_ROOT

from .schemas import DocumentChunk, RAGStats, RetrievedChunk


COLLECTION_NAME = "ramanagent_rag_chunks"


class VectorStore:
    def __init__(self, *, provider: str | None = None, persist_dir: str | Path | None = None) -> None:
        self.provider = str(provider or os.getenv("VECTOR_DB_PROVIDER") or "chroma").strip().lower()
        self.persist_dir = Path(persist_dir or os.getenv("VECTOR_DB_DIR") or PROJECT_ROOT / "storage" / "vector_db")
        if not self.persist_dir.is_absolute():
            self.persist_dir = PROJECT_ROOT / self.persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client: Any = None
        self._collection: Any = None
        self._availability_error: str | None = None

    def is_available(self) -> bool:
        if self.provider == "mock":
            return True
        try:
            self._get_collection()
            return True
        except Exception as exc:
            self._availability_error = str(exc)
            return False

    def add_chunks(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> list[str]:
        if not chunks:
            return []
        if len(chunks) != len(embeddings):
            raise ValueError("chunks 与 embeddings 数量不一致。")
        if self.provider == "mock":
            return self._mock_add(chunks, embeddings)
        collection = self._get_collection()
        ids = [chunk.chunk_id for chunk in chunks]
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=[chunk.text for chunk in chunks],
            metadatas=[self._metadata(chunk) for chunk in chunks],
        )
        return ids

    def search(self, query_embedding: list[float], filters: dict[str, Any], top_k: int = 6) -> list[RetrievedChunk]:
        if self.provider == "mock":
            return self._mock_search(query_embedding, filters, top_k=top_k)
        collection = self._get_collection()
        where = self._chroma_where(filters)
        result = collection.query(query_embeddings=[query_embedding], n_results=max(1, int(top_k or 6)), where=where or None)
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        chunks = []
        for index, chunk_id in enumerate(ids):
            metadata = dict(metadatas[index] or {})
            distance = float(distances[index]) if index < len(distances) and distances[index] is not None else None
            chunks.append(self._retrieved_from_metadata(chunk_id, documents[index] if index < len(documents) else "", metadata, distance))
        return chunks

    def search_conversation(self, query_embedding: list[float], *, user_id: str, conversation_id: str, file_ids: list[str] | None = None, top_k: int = 6) -> list[RetrievedChunk]:
        filters: dict[str, Any] = {"rag_scope": "conversation", "user_id": user_id, "conversation_id": conversation_id}
        if file_ids:
            filters["file_id"] = list(file_ids)
        return self.search(query_embedding, filters, top_k=top_k)

    def search_knowledge_base(self, query_embedding: list[float], *, knowledge_base_ids: list[str], top_k: int = 6) -> list[RetrievedChunk]:
        if not knowledge_base_ids:
            return []
        return self.search(query_embedding, {"rag_scope": "knowledge_base", "knowledge_base_id": list(knowledge_base_ids)}, top_k=top_k)

    def delete_by_file(self, file_id: str, user_id: str) -> None:
        self._delete_where({"rag_scope": "conversation", "file_id": file_id, "user_id": user_id})

    def delete_by_conversation(self, conversation_id: str, user_id: str) -> None:
        self._delete_where({"rag_scope": "conversation", "conversation_id": conversation_id, "user_id": user_id})

    def delete_by_knowledge_base_file(self, knowledge_base_id: str, kb_file_id: str) -> None:
        self._delete_where({"rag_scope": "knowledge_base", "knowledge_base_id": knowledge_base_id, "kb_file_id": kb_file_id})

    def delete_by_knowledge_base(self, knowledge_base_id: str) -> None:
        self._delete_where({"rag_scope": "knowledge_base", "knowledge_base_id": knowledge_base_id})

    def get_stats(self) -> dict[str, Any]:
        stats = RAGStats(
            available=self.is_available(),
            vector_provider=self.provider,
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "mock"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "mock-hash-embedding"),
            collection_name=COLLECTION_NAME,
            error_message=self._availability_error,
        )
        payload = stats.to_dict()
        payload["provider"] = self.provider
        if self.provider == "mock":
            payload["count"] = len(self._mock_load())
        return payload

    def _get_collection(self):
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ModuleNotFoundError as exc:
            raise RuntimeError("当前环境未安装 chromadb，向量检索不可用。") from exc
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(COLLECTION_NAME)
        return self._collection

    def _metadata(self, chunk: DocumentChunk) -> dict[str, Any]:
        metadata = {
            "rag_scope": chunk.rag_scope,
            "user_id": chunk.user_id or "",
            "conversation_id": chunk.conversation_id or "",
            "file_id": chunk.file_id or "",
            "filename": chunk.filename,
            "source_name": chunk.filename,
            "source_type": chunk.source_type,
            "page": "" if chunk.page is None else str(chunk.page),
            "sheet": chunk.sheet or "",
            "section": chunk.section or "",
            "chunk_index": int(chunk.chunk_index or 0),
            "knowledge_base_id": chunk.knowledge_base_id or "",
            "knowledge_base_name": chunk.knowledge_base_name or "",
            "kb_file_id": chunk.kb_file_id or "",
            "source_group": chunk.source_group,
        }
        for key, value in (chunk.metadata or {}).items():
            if isinstance(value, (str, int, float, bool)) and key not in metadata:
                metadata[key] = value
        return metadata

    def _chroma_where(self, filters: dict[str, Any]) -> dict[str, Any]:
        parts = []
        for key, value in (filters or {}).items():
            if isinstance(value, list):
                parts.append({key: {"$in": [str(item) for item in value]}})
            else:
                parts.append({key: str(value)})
        if not parts:
            return {}
        if len(parts) == 1:
            return parts[0]
        return {"$and": parts}

    def _retrieved_from_metadata(self, chunk_id: str, text: str, metadata: dict[str, Any], distance: float | None) -> RetrievedChunk:
        score = None if distance is None else 1.0 / (1.0 + max(0.0, distance))
        return RetrievedChunk(
            chunk_id=chunk_id,
            file_id=metadata.get("file_id") or None,
            conversation_id=metadata.get("conversation_id") or None,
            user_id=metadata.get("user_id") or None,
            filename=metadata.get("filename") or metadata.get("source_name") or "",
            source_type=metadata.get("source_type") or "file",
            text=text,
            page=metadata.get("page") or None,
            sheet=metadata.get("sheet") or None,
            section=metadata.get("section") or None,
            chunk_index=int(metadata.get("chunk_index") or 0),
            metadata=metadata,
            rag_scope=metadata.get("rag_scope") or "conversation",
            knowledge_base_id=metadata.get("knowledge_base_id") or None,
            knowledge_base_name=metadata.get("knowledge_base_name") or None,
            kb_file_id=metadata.get("kb_file_id") or None,
            source_group=metadata.get("source_group") or "conversation_file",
            score=score,
            distance=distance,
            retrieval_mode="vector",
        )

    def _delete_where(self, filters: dict[str, Any]) -> None:
        if self.provider == "mock":
            items = [item for item in self._mock_load() if not self._matches(item["metadata"], filters)]
            self._mock_save(items)
            return
        if not self.is_available():
            return
        self._get_collection().delete(where=self._chroma_where(filters))

    def _mock_path(self) -> Path:
        return self.persist_dir / "mock_vectors.json"

    def _mock_load(self) -> list[dict[str, Any]]:
        path = self._mock_path()
        if not path.exists():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _mock_save(self, items: list[dict[str, Any]]) -> None:
        self._mock_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def _mock_add(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> list[str]:
        existing = {item.get("id"): item for item in self._mock_load()}
        for chunk, embedding in zip(chunks, embeddings):
            existing[chunk.chunk_id] = {
                "id": chunk.chunk_id,
                "embedding": embedding,
                "document": chunk.text,
                "metadata": self._metadata(chunk),
            }
        self._mock_save(list(existing.values()))
        return [chunk.chunk_id for chunk in chunks]

    def _mock_search(self, query_embedding: list[float], filters: dict[str, Any], top_k: int) -> list[RetrievedChunk]:
        results = []
        for item in self._mock_load():
            metadata = dict(item.get("metadata") or {})
            if not self._matches(metadata, filters):
                continue
            distance = 1.0 - self._cosine(query_embedding, list(item.get("embedding") or []))
            results.append((distance, item))
        results.sort(key=lambda pair: pair[0])
        return [
            self._retrieved_from_metadata(str(item.get("id")), str(item.get("document") or ""), dict(item.get("metadata") or {}), distance)
            for distance, item in results[: max(1, int(top_k or 6))]
        ]

    def _matches(self, metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, value in (filters or {}).items():
            current = str(metadata.get(key) or "")
            if isinstance(value, list):
                if current not in {str(item) for item in value}:
                    return False
            elif current != str(value):
                return False
        return True

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        size = min(len(left), len(right))
        dot = sum(left[index] * right[index] for index in range(size))
        left_norm = math.sqrt(sum(value * value for value in left[:size])) or 1.0
        right_norm = math.sqrt(sum(value * value for value in right[:size])) or 1.0
        return dot / (left_norm * right_norm)
