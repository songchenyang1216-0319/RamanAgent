from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from .schemas import RetrievedChunk


def _tokens(text: str) -> set[str]:
    lowered = str(text or "").lower()
    parts = re.findall(r"[0-9a-zA-Z_]+|[\u4e00-\u9fa5]{1,4}", lowered)
    return {part for part in parts if part.strip()}


@dataclass
class RerankResult:
    chunks: list[RetrievedChunk]
    info: dict[str, Any]


class RAGReranker:
    """Lightweight reranker for mixed RAG.

    The default provider is deterministic and dependency-free. It improves demo
    quality without requiring a cross-encoder model, while keeping a clear seam
    for future local/remote rerank providers.
    """

    def __init__(self, *, enabled: bool | None = None, provider: str | None = None) -> None:
        self.enabled = bool(str(os.getenv("RAG_ENABLE_RERANK", "false")).lower() == "true") if enabled is None else bool(enabled)
        self.provider = str(provider or os.getenv("RAG_RERANK_PROVIDER") or "lexical").strip().lower()
        self.vector_weight = float(os.getenv("RAG_RERANK_VECTOR_WEIGHT", "0.65") or 0.65)
        self.keyword_weight = float(os.getenv("RAG_RERANK_KEYWORD_WEIGHT", "0.35") or 0.35)
        self.min_per_source = max(0, int(os.getenv("RAG_MIXED_MIN_PER_SOURCE", "1") or 1))

    def rerank(self, query: str, chunks: list[RetrievedChunk], *, top_k: int, enforce_source_balance: bool = False) -> RerankResult:
        if not chunks:
            return RerankResult([], self._info(applied=False, reason="no_chunks", before=0, after=0))
        if not self.enabled:
            selected = self._balance(chunks, top_k=top_k) if enforce_source_balance else chunks[:top_k]
            return RerankResult(selected, self._info(applied=False, reason="disabled", before=len(chunks), after=len(selected)))
        if self.provider not in {"lexical", "mock", "local"}:
            selected = self._balance(chunks, top_k=top_k) if enforce_source_balance else chunks[:top_k]
            return RerankResult(selected, self._info(applied=False, reason=f"unsupported_provider:{self.provider}", before=len(chunks), after=len(selected)))

        query_tokens = _tokens(query)
        scored: list[tuple[float, RetrievedChunk]] = []
        for chunk in chunks:
            chunk_tokens = _tokens(chunk.text)
            overlap = len(query_tokens & chunk_tokens)
            keyword_score = overlap / max(1, len(query_tokens))
            vector_score = float(chunk.score or 0.0)
            score = (vector_score * self.vector_weight) + (keyword_score * self.keyword_weight)
            chunk.metadata = dict(chunk.metadata or {})
            chunk.metadata["rerank_score"] = score
            chunk.metadata["rerank_keyword_overlap"] = overlap
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        ranked = [chunk for _, chunk in scored]
        selected = self._balance(ranked, top_k=top_k) if enforce_source_balance else ranked[:top_k]
        return RerankResult(
            selected,
            self._info(applied=True, reason="ok", before=len(chunks), after=len(selected), provider=self.provider),
        )

    def _balance(self, chunks: list[RetrievedChunk], *, top_k: int) -> list[RetrievedChunk]:
        top_k = max(1, int(top_k or 6))
        if self.min_per_source <= 0:
            return chunks[:top_k]
        conversation = [chunk for chunk in chunks if chunk.rag_scope == "conversation"]
        knowledge_base = [chunk for chunk in chunks if chunk.rag_scope == "knowledge_base"]
        selected: list[RetrievedChunk] = []
        for group in (conversation, knowledge_base):
            for chunk in group[: self.min_per_source]:
                if chunk not in selected and len(selected) < top_k:
                    selected.append(chunk)
        for chunk in chunks:
            if len(selected) >= top_k:
                break
            if chunk not in selected:
                selected.append(chunk)
        return selected

    def _info(self, *, applied: bool, reason: str, before: int, after: int, provider: str | None = None) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "applied": applied,
            "provider": provider or self.provider,
            "reason": reason,
            "input_count": before,
            "output_count": after,
            "min_per_source": self.min_per_source,
        }
