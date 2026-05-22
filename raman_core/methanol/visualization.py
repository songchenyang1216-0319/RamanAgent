"""光谱阶段图生成。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .config import FIGURE_DIR, ensure_dirs


def _sanitize_name(sample_name: str) -> str:
    return Path(sample_name).stem.replace(" ", "_")


def _save_single_stage_figure(
    axis: np.ndarray,
    values: np.ndarray,
    title: str,
    output_path: Path,
) -> str:
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(axis, values)
    ax.set_title(title)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return str(output_path)


def save_stage_figures(
    sample_name: str,
    common_axis: np.ndarray,
    raw: np.ndarray,
    preprocessed: np.ndarray,
    cdae: np.ndarray,
    final: np.ndarray,
    titles: dict | None = None,
) -> dict:
    """保存四阶段光谱图并返回路径字典。"""
    ensure_dirs()
    name = _sanitize_name(sample_name)
    titles = titles or {}

    raw_path = FIGURE_DIR / f"{name}_raw.png"
    preprocessed_path = FIGURE_DIR / f"{name}_preprocessed.png"
    cdae_path = FIGURE_DIR / f"{name}_cdae.png"
    final_path = FIGURE_DIR / f"{name}_final.png"

    return {
        "raw": _save_single_stage_figure(common_axis, raw, titles.get("title_plot_1", "统一波数轴后的原始光谱"), raw_path),
        "preprocessed": _save_single_stage_figure(common_axis, preprocessed, titles.get("title_plot_2", "SG平滑 + ALS去基线 + 归一化后光谱"), preprocessed_path),
        "cdae": _save_single_stage_figure(common_axis, cdae, titles.get("title_plot_3", "SG平滑 + ALS去基线 + 归一化 + CDAE去噪后光谱"), cdae_path),
        "final": _save_single_stage_figure(common_axis, final, titles.get("title_plot_4", "最终 CAE+ 基线修正后光谱"), final_path),
    }
