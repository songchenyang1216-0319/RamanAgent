"""Deep learning placeholders with strict model-file checks."""

from __future__ import annotations

from typing import Any

from .algorithm_schema import AlgorithmRunOutput, RamanPipelineError


def model_missing(algorithm_id: str) -> AlgorithmRunOutput:
    raise RamanPipelineError(f"深度学习算法 {algorithm_id} 尚未配置模型文件，不能执行。")


def cnn_1d_classifier(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return model_missing("cnn_1d_classifier")


def cnn_1d_regressor(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return model_missing("cnn_1d_regressor")


def autoencoder_denoise(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return model_missing("autoencoder_denoise")


def cdae_denoise(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return model_missing("cdae_denoise")


def cae_baseline_prediction(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return model_missing("cae_baseline_prediction")

