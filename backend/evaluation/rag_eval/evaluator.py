from __future__ import annotations

import time
from typing import Any

from backend.evaluation.rag_eval.metrics import compute_metrics
from backend.services.rag import RAGService


class RAGEvaluator:
    def __init__(self, service: RAGService | None = None) -> None:
        self.service = service or RAGService()

    def evaluate(self, dataset: list[dict[str, Any]], *, user_id: str = "default_user", conversation_id: str = "") -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for item in dataset:
            query = str(item.get("query") or "")
            started = time.perf_counter()
            answer = self.service.answer_with_rag(
                query,
                user_id,
                str(item.get("conversation_id") or conversation_id),
                file_ids=list(item.get("file_ids") or []),
                knowledge_base_ids=list(item.get("knowledge_base_ids") or []),
                rag_scope=str(item.get("rag_scope") or "conversation"),
            ).to_dict()
            latency_ms = int((time.perf_counter() - started) * 1000)
            citations = answer.get("citations") or []
            expected_sources = {str(value) for value in (item.get("expected_source_ids") or [])}
            expected_text = [str(value) for value in (item.get("expected_answer_contains") or [])]
            answer_text = str(answer.get("answer") or "")
            cited_sources = {
                str(citation.get("source_id") or citation.get("file_id") or citation.get("knowledge_base_id") or "")
                for citation in citations
            }
            should_answer = bool(item.get("should_answer", True))
            rows.append(
                {
                    "query": query,
                    "should_answer": should_answer,
                    "retrieval_hit": not expected_sources or bool(expected_sources & cited_sources),
                    "citation_hit": bool(citations) and (not expected_sources or bool(expected_sources & cited_sources)),
                    "answer_grounded": all(fragment in answer_text for fragment in expected_text) if expected_text else bool(citations),
                    "no_answer_correct": (not should_answer) and ("未找到" in answer_text or not answer.get("success")),
                    "latency_ms": latency_ms,
                    "answer": answer_text,
                    "citations": citations,
                }
            )
        return {"success": True, "metrics": compute_metrics(rows), "rows": rows}

