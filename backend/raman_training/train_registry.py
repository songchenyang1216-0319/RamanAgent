from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.services.workspace_manager import now_iso, read_json, write_json
from raman_core.methanol.config import PROJECT_ROOT


MODEL_REGISTRY_PATH = PROJECT_ROOT / "storage" / "raman_training_models.json"


class RamanTrainRegistry:
    def list_models(self) -> list[dict[str, Any]]:
        value = read_json(MODEL_REGISTRY_PATH, [])
        return value if isinstance(value, list) else []

    def register_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = {
            "model_id": str(payload.get("model_id") or uuid4().hex),
            "model_type": payload.get("model_type"),
            "target": payload.get("target"),
            "preprocess_pipeline_id": payload.get("preprocess_pipeline_id"),
            "train_dataset_id": payload.get("train_dataset_id"),
            "metrics": dict(payload.get("metrics") or {}),
            "model_file": payload.get("model_file"),
            "scaler_file": payload.get("scaler_file"),
            "created_at": now_iso(),
            "version": payload.get("version") or "v1",
            "active": bool(payload.get("active", False)),
        }
        items = self.list_models()
        items.append(item)
        write_json(MODEL_REGISTRY_PATH, items)
        return item

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        return next((dict(item) for item in self.list_models() if str(item.get("model_id")) == str(model_id)), None)

    def activate(self, model_id: str) -> dict[str, Any]:
        items = self.list_models()
        target = None
        for item in items:
            item["active"] = str(item.get("model_id")) == str(model_id)
            if item["active"]:
                target = item
        if target is None:
            raise KeyError("模型不存在。")
        write_json(MODEL_REGISTRY_PATH, items)
        return dict(target)

