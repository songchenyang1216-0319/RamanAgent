from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DocumentChunk:
    chunk_id: str
    file_id: str | None
    conversation_id: str | None
    user_id: str | None
    filename: str
    source_type: str = "file"
    text: str = ""
    page: str | int | None = None
    sheet: str | None = None
    section: str | None = None
    chunk_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    rag_scope: str = "conversation"
    knowledge_base_id: str | None = None
    knowledge_base_name: str | None = None
    kb_file_id: str | None = None
    source_group: str = "conversation_file"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievedChunk(DocumentChunk):
    score: float | None = None
    distance: float | None = None
    retrieval_mode: str = "vector"


@dataclass
class IndexResult:
    success: bool
    file_id: str | None
    user_id: str
    conversation_id: str | None = None
    rag_scope: str = "conversation"
    knowledge_base_id: str | None = None
    kb_file_id: str | None = None
    status: str = "pending"
    chunk_count: int = 0
    vector_provider: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RAGSearchResult:
    success: bool
    query: str
    rag_scope: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    conversation_chunks: list[RetrievedChunk] = field(default_factory=list)
    knowledge_base_chunks: list[RetrievedChunk] = field(default_factory=list)
    retrieval_mode: str = "none"
    rerank: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    source_breakdown: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chunks"] = [chunk.to_dict() for chunk in self.chunks]
        payload["conversation_chunks"] = [chunk.to_dict() for chunk in self.conversation_chunks]
        payload["knowledge_base_chunks"] = [chunk.to_dict() for chunk in self.knowledge_base_chunks]
        return payload


@dataclass
class RAGAnswer:
    success: bool
    query: str
    answer: str
    rag_scope: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieved_chunks: list[dict[str, Any]] = field(default_factory=list)
    source_breakdown: dict[str, Any] = field(default_factory=dict)
    retrieval_mode: str = "none"
    rerank: dict[str, Any] = field(default_factory=dict)
    model_info: dict[str, Any] = field(default_factory=dict)
    rag: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RAGStats:
    available: bool
    vector_provider: str
    embedding_provider: str
    embedding_model: str
    collection_name: str = "ramanagent_rag_chunks"
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
