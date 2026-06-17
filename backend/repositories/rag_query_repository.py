from __future__ import annotations

from typing import Any

from .base import SQLiteRepository, dumps_json


class RagQueryRepository(SQLiteRepository):
    table_name = "rag_queries"
    id_field = "rag_query_id"

    def record_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = dict(payload or {})
        for key in (
            "file_ids_json",
            "knowledge_base_ids_json",
            "retrieved_chunks_json",
            "retrieved_chunk_ids_json",
            "citations_json",
            "model_info_json",
            "source_breakdown_json",
        ):
            if not isinstance(item.get(key), str):
                item[key] = dumps_json(item.get(key) or ([] if key.endswith("ids_json") or key in {"retrieved_chunks_json", "citations_json"} else {}))
        item.setdefault("query_id", item.get("rag_query_id"))
        return self.create(item)

