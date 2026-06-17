from __future__ import annotations

from typing import Any

from backend.raman_evaluation.metrics import regression_metrics


def evaluate_regression_model(model: Any, features: list[list[float]], targets: list[float]) -> dict[str, Any]:
    predictions = model.predict(features).tolist()
    return regression_metrics([float(value) for value in targets], [float(value) for value in predictions])

