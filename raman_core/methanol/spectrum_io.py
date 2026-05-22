"""光谱文件读取与数据集装载。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def parse_concentration(file_name: str) -> float | None:
    """从文件名中解析浓度标签。"""
    match = re.search(r"-(\d+(?:\.\d+)?)-", file_name)
    return float(match.group(1)) if match else None


def read_csv_spectrum(file_path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """读取单个 CSV 光谱文件并返回排序后的 x/y 数组。"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {path}")

    df = None
    errors: list[str] = []
    for enc in ("utf-8", "gbk", "utf-8-sig"):
        try:
            df = pd.read_csv(path, encoding=enc)
            break
        except Exception as exc:
            errors.append(f"{enc}: {exc}")

    if df is None:
        raise ValueError(f"CSV 读取失败，编码尝试均未成功: {path}\n" + "\n".join(errors))
    if df.shape[1] < 2:
        raise ValueError(f"CSV 至少需要两列数据，默认第一列为 Raman shift、第二列为 intensity: {path}")

    x = pd.to_numeric(df.iloc[:, 0], errors="coerce")
    y = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    mask = x.notna() & y.notna()
    x_arr = x[mask].to_numpy(dtype=float)
    y_arr = y[mask].to_numpy(dtype=float)

    if len(x_arr) < 10 or len(y_arr) < 10:
        raise ValueError(f"CSV 有效数值点过少，至少需要 10 个点: {path}")

    order = np.argsort(x_arr)
    return x_arr[order], y_arr[order]


def build_common_axis(x_list: Iterable[np.ndarray], target_length: int = 1024) -> np.ndarray:
    """根据多条光谱的重叠范围构建统一波数轴。"""
    x_list = list(x_list)
    min_right = min(np.max(x) for x in x_list)
    max_left = max(np.min(x) for x in x_list)
    if min_right <= max_left:
        raise ValueError("所有光谱没有共同的波数范围，无法统一插值。")
    return np.linspace(max_left, min_right, target_length)


def load_labeled_spectra(data_folder: str | Path, target_length: int = 1024) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """读取目录中的全部带标签 CSV 光谱并插值到公共坐标轴。"""
    folder = Path(data_folder)
    if not folder.exists():
        raise FileNotFoundError(f"数据目录不存在: {folder}")

    from .preprocess import interpolate_to_axis

    x_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []
    conc_list: list[float] = []
    names: list[str] = []

    for path in sorted(folder.glob("*.csv")):
        conc = parse_concentration(path.name)
        if conc is None:
            continue
        try:
            x, y = read_csv_spectrum(path)
        except ValueError as exc:
            print(f"跳过文件（读取失败）: {path.name} | {exc}")
            continue

        x_list.append(x)
        y_list.append(y)
        conc_list.append(conc)
        names.append(path.name)

    if not x_list:
        raise ValueError("没有读取到有效的 CSV 光谱数据。")

    common_axis = build_common_axis(x_list, target_length=target_length)
    aligned = np.array([interpolate_to_axis(x, y, common_axis) for x, y in zip(x_list, y_list)], dtype=np.float32)
    concentrations = np.array(conc_list, dtype=np.float32)
    return aligned, concentrations, common_axis, names
