from __future__ import annotations

from typing import Any

from .base import SQLiteRepository, dumps_json


class PipelineRunRepository(SQLiteRepository):
    table_name = "pipeline_runs"
    id_field = "pipeline_run_id"

    def record_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = dict(payload or {})
        item["pipeline_request_json"] = dumps_json(item.get("pipeline_request_json") or item.get("pipeline_request") or {})
        item["pipeline_result_json"] = dumps_json(item.get("pipeline_result_json") or item.get("pipeline_result") or {})
        item["artifacts_json"] = dumps_json(item.get("artifacts_json") or item.get("artifacts") or [])
        return self.create(item)

