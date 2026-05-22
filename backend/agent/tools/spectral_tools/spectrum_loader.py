"""Raman CSV 光谱读取工具。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_raman_csv(csv_path: str | Path) -> dict:
    """读取两列 Raman CSV，并过滤空值和非数字行。"""
    try:
        path = Path(csv_path)
        if not path.exists():
            return {"success": False, "error_message": f"CSV 文件不存在: {path}"}
        if path.suffix.lower() != ".csv":
            return {"success": False, "error_message": "只支持 CSV 光谱文件。"}

        last_error = None
        frame = None
        for encoding in ("utf-8-sig", "utf-8", "gbk", "latin1"):
            try:
                frame = pd.read_csv(path, header=None, encoding=encoding)
                break
            except Exception as exc:
                last_error = exc
        if frame is None:
            return {"success": False, "error_message": f"读取 CSV 失败: {last_error}"}
        if frame.shape[1] < 2:
            return {"success": False, "error_message": "CSV 至少需要两列：波数和强度。"}

        numeric = frame.iloc[:, :2].apply(pd.to_numeric, errors="coerce").dropna()
        if numeric.empty or len(numeric) < 5:
            return {"success": False, "error_message": "CSV 中有效数值点太少，无法进行光谱分析。"}

        x = numeric.iloc[:, 0].to_numpy(dtype=float)
        y = numeric.iloc[:, 1].to_numpy(dtype=float)
        order = np.argsort(x)
        x = x[order]
        y = y[order]

        finite_mask = np.isfinite(x) & np.isfinite(y)
        x = x[finite_mask]
        y = y[finite_mask]
        if len(x) < 5:
            return {"success": False, "error_message": "过滤无效值后有效光谱点太少。"}

        return {
            "success": True,
            "x": x.tolist(),
            "y": y.tolist(),
            "points": int(len(x)),
            "x_min": float(np.min(x)),
            "x_max": float(np.max(x)),
            "y_min": float(np.min(y)),
            "y_max": float(np.max(y)),
        }
    except Exception as exc:
        return {"success": False, "error_message": f"读取光谱失败: {exc}"}

