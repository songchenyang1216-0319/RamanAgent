"""Classical ML algorithms for feature-based Raman experiments."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.cross_decomposition import PLSRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Lasso, LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.svm import SVR

from .algorithm_schema import AlgorithmRunOutput, RamanPipelineError


def _current_feature(data: dict[str, Any]) -> np.ndarray:
    if "features" in data and isinstance(data["features"], dict):
        values = [float(v) for v in data["features"].values() if isinstance(v, (int, float))]
        if values:
            return np.asarray(values, dtype=float).reshape(1, -1)
    y = data.get("intensity")
    if y is None:
        raise RamanPipelineError("机器学习算法需要当前光谱或 features。")
    arr = np.asarray(y, dtype=float)
    if arr.size == 0:
        raise RamanPipelineError("当前光谱强度为空，无法构建特征。")
    return arr.reshape(1, -1)


def _training_data(params: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    features = params.get("train_features")
    targets = params.get("train_targets")
    if not isinstance(features, list) or not isinstance(targets, list):
        raise RamanPipelineError("机器学习算法需要 train_features 和 train_targets 参数，当前未提供训练数据。")
    x_train = np.asarray(features, dtype=float)
    y_train = np.asarray(targets, dtype=float)
    if x_train.ndim != 2 or y_train.ndim != 1:
        raise RamanPipelineError("参数错误：train_features 必须是二维数组，train_targets 必须是一维数组。")
    if len(x_train) != len(y_train) or len(y_train) < 2:
        raise RamanPipelineError("参数错误：训练样本数必须一致且不少于 2。")
    return x_train, y_train


def _fit_predict(data: dict[str, Any], params: dict[str, Any], model: Any, model_name: str) -> AlgorithmRunOutput:
    x_train, y_train = _training_data(params)
    current = _current_feature(data)
    if current.shape[1] != x_train.shape[1]:
        raise RamanPipelineError("当前光谱特征维度与 train_features 不一致。")
    model.fit(x_train, y_train)
    prediction = float(np.asarray(model.predict(current)).ravel()[0])
    train_pred = np.asarray(model.predict(x_train)).ravel()
    metrics = {
        "prediction": prediction,
        "train_mae": float(mean_absolute_error(y_train, train_pred)),
        "train_r2": float(r2_score(y_train, train_pred)) if len(y_train) > 1 else None,
        "model": model_name,
    }
    out = dict(data)
    out.setdefault("ml_predictions", {})[model_name] = prediction
    return AlgorithmRunOutput(data=out, metrics=metrics)


def svr_regressor(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return _fit_predict(data, params, SVR(C=float(params.get("C", 1.0)), epsilon=float(params.get("epsilon", 0.1))), "svr_regressor")


def random_forest_regressor(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return _fit_predict(
        data,
        params,
        RandomForestRegressor(n_estimators=int(params.get("n_estimators", 80)), random_state=int(params.get("random_state", 42))),
        "random_forest_regressor",
    )


def pls_regressor(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return _fit_predict(data, params, PLSRegression(n_components=int(params.get("n_components", 2))), "pls_regressor")


def linear_regressor(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return _fit_predict(data, params, LinearRegression(), "linear_regressor")


def ridge_regressor(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return _fit_predict(data, params, Ridge(alpha=float(params.get("alpha", 1.0))), "ridge_regressor")


def lasso_regressor(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return _fit_predict(data, params, Lasso(alpha=float(params.get("alpha", 0.01)), max_iter=10000), "lasso_regressor")

