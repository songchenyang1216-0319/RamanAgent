from __future__ import annotations

from typing import Any


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(1, len(rows))
    retrieval_hits = sum(1 for row in rows if row.get("retrieval_hit"))
    citation_hits = sum(1 for row in rows if row.get("citation_hit"))
    grounded = sum(1 for row in rows if row.get("answer_grounded"))
    no_answer = [row for row in rows if row.get("should_answer") is False]
    no_answer_hits = sum(1 for row in no_answer if row.get("no_answer_correct"))
    latencies = [int(row.get("latency_ms") or 0) for row in rows]
    return {
        "retrieval_hit_rate": retrieval_hits / total,
        "citation_accuracy": citation_hits / total,
        "answer_groundedness": grounded / total,
        "faithfulness": grounded / total,
        "no_answer_accuracy": (no_answer_hits / max(1, len(no_answer))) if no_answer else None,
        "latency_ms": sum(latencies) / max(1, len(latencies)),
        "total": len(rows),
    }

