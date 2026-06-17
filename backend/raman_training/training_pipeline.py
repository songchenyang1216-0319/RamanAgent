from __future__ import annotations

from typing import Any

from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Lasso, LinearRegression, Ridge
from sklearn.neighbors import KNeighborsRegressor
from sklearn.cross_decomposition import PLSRegression
from sklearn.svm import SVR

from backend.raman_training.model_evaluator import evaluate_regression_model
from backend.raman_training.model_exporter import export_model
from backend.raman_training.train_registry import RamanTrainRegistry


MODEL_FACTORIES = {
    "SVR": lambda params: SVR(**params),
    "RandomForestRegressor": lambda params: RandomForestRegressor(**({"n_estimators": 100, "random_state": 42} | params)),
    "PLSRegression": lambda params: PLSRegression(**({"n_components": 2} | params)),
    "Ridge": lambda params: Ridge(**params),
    "Lasso": lambda params: Lasso(**({"alpha": 0.01} | params)),
    "LinearRegression": lambda params: LinearRegression(**params),
    "KNNRegressor": lambda params: KNeighborsRegressor(**params),
}


class RamanTrainingPipeline:
    def __init__(self, registry: RamanTrainRegistry | None = None) -> None:
        self.registry = registry or RamanTrainRegistry()

    def train(self, payload: dict[str, Any]) -> dict[str, Any]:
        model_type = str(payload.get("model_type") or "SVR")
        if model_type == "1D-CNN":
            return {"success": False, "error_message": "1D-CNN 训练暂为占位能力，请先使用传统机器学习模型。"}
        features = payload.get("features") or []
        targets = payload.get("targets") or []
        if not features or not targets:
            return {"success": False, "error_message": "没有训练数据：请提供 features 和 targets，或先创建带标签的数据集。"}
        if model_type not in MODEL_FACTORIES:
            return {"success": False, "error_message": f"暂不支持的模型类型：{model_type}"}
        model = MODEL_FACTORIES[model_type](dict(payload.get("params") or {}))
        model.fit(features, targets)
        metrics = evaluate_regression_model(model, features, targets)
        model_file = export_model(model, model_type=model_type, target=str(payload.get("target") or "methanol"))
        record = self.registry.register_model(
            {
                "model_type": model_type,
                "target": payload.get("target") or "methanol",
                "preprocess_pipeline_id": payload.get("preprocess_pipeline_id"),
                "train_dataset_id": payload.get("train_dataset_id"),
                "metrics": metrics,
                "model_file": model_file,
                "version": payload.get("version") or "v1",
            }
        )
        return {"success": True, "model": record, "metrics": metrics}

