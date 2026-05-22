"""可信度评估逻辑。"""

from __future__ import annotations

import numpy as np


def calc_train_distance_threshold(latent_train: np.ndarray, k: int = 5, percentile: float = 95.0) -> float:
    """根据训练集编码向量估计可信度阈值。"""
    n = latent_train.shape[0]
    dists = []
    for i in range(n):
        diff = latent_train - latent_train[i]
        cur = np.sqrt(np.sum(diff ** 2, axis=1))
        cur = np.sort(cur)
        knn_mean = np.mean(cur[1:k + 1])
        dists.append(knn_mean)
    return float(np.percentile(dists, percentile))


def calculate_confidence(
    current_latent: np.ndarray,
    latent_train: np.ndarray,
    threshold: float,
    k: int = 5,
) -> dict:
    """计算当前样本与训练集潜空间距离，并给出可信度状态。"""
    distances = np.sqrt(np.sum((latent_train - current_latent) ** 2, axis=1))
    mean_knn_dist = float(np.mean(np.sort(distances)[:k]))
    status = "可信度正常" if mean_knn_dist <= threshold else "样本偏离训练集，预测仅供参考"
    return {
        "knn_distance": mean_knn_dist,
        "threshold": float(threshold),
        "status": status,
    }
