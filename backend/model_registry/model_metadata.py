"""模型注册表默认元数据。"""

from __future__ import annotations


DEFAULT_MODEL_VERSION = "methanol_v1"
DEFAULT_REQUIRED_FILES = [
    "cdae_display_model.pt",
    "cdae_reg_model.pt",
    "caeplus_model.pt",
    "svr_model.pkl",
    "rf_model.pkl",
    "scaler.pkl",
    "common_axis.npy",
    "latent_train.npy",
    "config.json",
]

DEFAULT_MODEL_REGISTRY = {
    "default_model": DEFAULT_MODEL_VERSION,
    "models": {
        DEFAULT_MODEL_VERSION: {
            "model_name": "Methanol Raman SVR/RF Fusion Model",
            "task": "methanol_concentration_prediction",
            "unit": "%",
            "algorithm": ["SVR", "RandomForest", "CDAE", "CAE+"],
            "artifact_dir": f"artifacts/{DEFAULT_MODEL_VERSION}",
            "legacy_artifact_dir": "artifacts",
            "required_files": DEFAULT_REQUIRED_FILES,
            "training_data": {
                "sample_count": 65,
                "spectrum_length": 1024,
                "concentration_range": [0, 100],
                "description": "甲醇 Raman CSV 数据集",
            },
            "metrics": {
                "rmse": None,
                "mae": None,
                "r2": None,
            },
            "status": "active",
            "config_file": "config.json",
            "metrics_file": "metrics.json",
            "training_meta_file": "training_meta.json",
            "preprocessing_pipeline": [
                "统一波数轴",
                "SG平滑",
                "ALS去基线",
                "CDAE去噪",
                "CAE+预测基线",
                "SVR/RF融合预测",
            ],
            "created_at": "2026-05-14",
            "notes": "初始甲醇预测模型版本",
        }
    },
}
