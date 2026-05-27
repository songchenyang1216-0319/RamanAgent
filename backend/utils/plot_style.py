"""Matplotlib 绘图样式配置。"""

from __future__ import annotations

import logging

import matplotlib
from matplotlib import font_manager


logger = logging.getLogger(__name__)
_STYLE_APPLIED = False


def apply_chinese_plot_style() -> None:
    """统一配置中文字体与负号显示，避免图表保存时刷屏 warning。"""
    global _STYLE_APPLIED
    if _STYLE_APPLIED:
        return

    preferred_fonts = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
    ]
    available_fonts: list[str] = []
    for font_name in preferred_fonts:
        try:
            font_manager.findfont(font_name, fallback_to_default=False)
        except Exception:
            continue
        available_fonts.append(font_name)

    if available_fonts:
        matplotlib.rcParams["font.sans-serif"] = available_fonts + ["DejaVu Sans"]
    else:
        logger.info("未检测到常见中文字体，将使用 Matplotlib 默认字体；中文标签可能仍出现 glyph warning。")
        matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    _STYLE_APPLIED = True
