"""Methanol-related Raman peak knowledge.

The entries here are intentionally phrased as hints, not as hard compound
identification rules. Raman peak assignment depends on instrument, solvent,
concentration, baseline handling, and sample conditions.
"""

from __future__ import annotations


METHANOL_PEAK_RANGES = [
    {
        "range": (1010.0, 1055.0),
        "label": "C-O stretching region",
        "possible_mode": "甲醇中 C-O 伸缩振动通常可能出现在这一带。",
        "caution": "需要结合浓度、溶剂和预处理结果判断，不能单凭该峰确认成分。",
    },
    {
        "range": (1120.0, 1165.0),
        "label": "CH3 rocking / C-O coupled region",
        "possible_mode": "可能与 CH3 摇摆或 C-O 相关耦合振动有关。",
        "caution": "该区域可能和其他有机物振动重叠，建议结合全谱形态。",
    },
    {
        "range": (1420.0, 1485.0),
        "label": "CH3 deformation region",
        "possible_mode": "常见于 CH3 变形振动相关区域。",
        "caution": "峰强会受背景和浓度影响，不能作为单独判据。",
    },
    {
        "range": (2800.0, 3000.0),
        "label": "C-H stretching region",
        "possible_mode": "可能对应 C-H 伸缩振动区。",
        "caution": "本项目常用波数范围未必覆盖该区，如未采集则不应推断。",
    },
    {
        "range": (3200.0, 3600.0),
        "label": "O-H stretching region",
        "possible_mode": "可能与 O-H 伸缩振动和氢键环境有关。",
        "caution": "水和背景也可能显著影响该区域。",
    },
]

BACKGROUND_OR_WATER_REGIONS = [
    {
        "range": (1550.0, 1700.0),
        "description": "水弯曲振动或背景信号可能影响该区域，解释时需要谨慎。",
    },
    {
        "range": (3200.0, 3600.0),
        "description": "水和 O-H 宽峰常可能影响高波数区域。",
    },
    {
        "range": (400.0, 500.0),
        "description": "低波数边缘可能更容易受到仪器背景或截断影响。",
    },
]

SPECTRAL_ARTIFACT_DESCRIPTIONS = {
    "noise": "随机噪声会抬高基线附近的小尖峰，使弱峰识别不稳定。",
    "fluorescence_background": "荧光背景通常表现为缓慢变化的宽基线，会影响峰强和回归输入。",
    "baseline_drift": "基线漂移会让不同波段整体抬升或降低，可能影响浓度预测稳定性。",
    "saturation": "饱和或削顶会压平峰顶，导致峰形和峰强失真。",
}


def find_peak_annotations(wavenumber: float) -> list[dict]:
    """Return cautious annotations for a Raman peak position."""
    annotations = []
    value = float(wavenumber)
    for item in METHANOL_PEAK_RANGES:
        low, high = item["range"]
        if low <= value <= high:
            annotations.append(
                {
                    "range": item["range"],
                    "label": item["label"],
                    "possible_mode": item["possible_mode"],
                    "caution": item["caution"],
                    "confidence": "possible",
                }
            )
    for item in BACKGROUND_OR_WATER_REGIONS:
        low, high = item["range"]
        if low <= value <= high:
            annotations.append(
                {
                    "range": item["range"],
                    "label": "background_or_water_region",
                    "possible_mode": item["description"],
                    "caution": "该提示只表示区域风险，不代表已经检出水或背景成分。",
                    "confidence": "caution",
                }
            )
    if not annotations:
        annotations.append(
            {
                "range": None,
                "label": "unassigned",
                "possible_mode": "当前峰位未落入内置甲醇常见提示区。",
                "caution": "建议结合全谱、样品背景和重复实验判断，不做确定成分归属。",
                "confidence": "unknown",
            }
        )
    return annotations


def annotate_peaks(peaks: list[dict]) -> list[dict]:
    """Attach cautious Raman knowledge annotations to detected peaks."""
    annotated = []
    for peak in peaks:
        item = dict(peak)
        item["knowledge_annotations"] = find_peak_annotations(float(item.get("wavenumber", 0.0)))
        annotated.append(item)
    return annotated
