"""CSV spectrum loading and validation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .algorithm_schema import AlgorithmRunOutput, RamanPipelineError


WAVENUMBER_HINTS = ("wavenumber", "wave_number", "raman_shift", "shift", "cm-1", "cm^-1", "波数", "拉曼位移")
INTENSITY_HINTS = ("intensity", "counts", "signal", "absorbance", "强度", "计数", "信号")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise RamanPipelineError(f"CSV 文件不存在：{path}")
    if path.suffix.lower() != ".csv":
        raise RamanPipelineError("文件格式错误：当前 Raman Pipeline 只支持 CSV 文件。")
    try:
        df = pd.read_csv(path)
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="gbk")
    except Exception as exc:
        raise RamanPipelineError(f"CSV 读取失败：{exc}") from exc
    if df.empty:
        raise RamanPipelineError("CSV 文件为空，无法读取光谱。")
    return df


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    numeric = []
    for column in df.columns:
        values = pd.to_numeric(df[column], errors="coerce")
        if values.notna().sum() >= 2:
            numeric.append(str(column))
    return numeric


def infer_columns(df: pd.DataFrame) -> tuple[str, str]:
    numeric = _numeric_columns(df)
    if len(numeric) < 2:
        raise RamanPipelineError("CSV 至少需要两列数值数据：波数列和强度列。")

    def score(column: str, hints: tuple[str, ...]) -> int:
        lowered = column.strip().lower().replace(" ", "_")
        return sum(1 for hint in hints if hint in lowered)

    wavenumber = max(numeric, key=lambda col: score(col, WAVENUMBER_HINTS))
    intensity_candidates = [col for col in numeric if col != wavenumber]
    intensity = max(intensity_candidates, key=lambda col: score(col, INTENSITY_HINTS))
    if score(wavenumber, WAVENUMBER_HINTS) == 0 and len(numeric) >= 2:
        wavenumber = numeric[0]
        intensity = numeric[1]
    return wavenumber, intensity


def dataframe_to_spectrum(df: pd.DataFrame, wavenumber_col: str | None = None, intensity_col: str | None = None) -> dict[str, Any]:
    w_col, y_col = (wavenumber_col, intensity_col) if wavenumber_col and intensity_col else infer_columns(df)
    try:
        x = pd.to_numeric(df[w_col], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(df[y_col], errors="coerce").to_numpy(dtype=float)
    except KeyError as exc:
        raise RamanPipelineError(f"找不到指定列：{exc}") from exc
    return {
        "wavenumber": x,
        "intensity": y,
        "source_columns": {"wavenumber": str(w_col), "intensity": str(y_col)},
        "dataframe": df,
    }


def _shape(data: dict[str, Any]) -> dict[str, Any]:
    x = data.get("wavenumber")
    y = data.get("intensity")
    return {
        "points": int(len(y)) if y is not None else 0,
        "wavenumber_points": int(len(x)) if x is not None else 0,
    }


def load_csv_spectrum(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    path = params.get("file_path") or data.get("file_path")
    if not path:
        raise RamanPipelineError("缺少 CSV 文件路径，请先上传或指定 file_path。")
    df = _read_csv(Path(str(path)))
    spectrum = dataframe_to_spectrum(
        df,
        str(params.get("wavenumber_column") or "").strip() or None,
        str(params.get("intensity_column") or "").strip() or None,
    )
    spectrum["file_path"] = str(path)
    return AlgorithmRunOutput(
        data=spectrum,
        metrics={
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "wavenumber_column": spectrum["source_columns"]["wavenumber"],
            "intensity_column": spectrum["source_columns"]["intensity"],
        },
    )


def validate_spectrum_csv(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    if "dataframe" not in data and data.get("file_path"):
        data.update(load_csv_spectrum(data, params).data)
    x = np.asarray(data.get("wavenumber"), dtype=float)
    y = np.asarray(data.get("intensity"), dtype=float)
    if x.size < 3 or y.size < 3:
        raise RamanPipelineError("有效光谱点少于 3 个，无法继续分析。")
    if x.size != y.size:
        raise RamanPipelineError("波数列和强度列长度不一致。")
    finite = np.isfinite(x) & np.isfinite(y)
    if finite.sum() < 3:
        raise RamanPipelineError("CSV 中有效数值点不足，可能包含过多空值或非数值内容。")
    warning = "" if finite.all() else f"检测到 {int((~finite).sum())} 个 NaN/Inf 点，建议执行 remove_nan_inf。"
    return AlgorithmRunOutput(
        data=data,
        metrics={
            "valid_points": int(finite.sum()),
            "invalid_points": int((~finite).sum()),
            "shape": _shape(data),
        },
        warning=warning,
    )


def infer_wavenumber_intensity_columns(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    df = data.get("dataframe")
    if df is None:
        path = params.get("file_path") or data.get("file_path")
        if not path:
            raise RamanPipelineError("缺少 CSV 数据，无法推断波数列和强度列。")
        df = _read_csv(Path(str(path)))
    w_col, y_col = infer_columns(df)
    return AlgorithmRunOutput(
        data={**data, "source_columns": {"wavenumber": w_col, "intensity": y_col}},
        metrics={"wavenumber_column": w_col, "intensity_column": y_col},
    )

