"""CSV 光谱读取 Skill。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agent.tools.spectral_tools.spectrum_loader import load_raman_csv

from .base import BaseSkill, SkillResult


class SpectrumLoaderSkill(BaseSkill):
    """负责读取并校验 CSV 光谱文件。"""

    name = "spectrum_loader_skill"
    description = "读取 CSV 光谱文件并返回基础统计信息。"

    def run(self, **kwargs: Any) -> SkillResult:
        file_path = str(kwargs.get("file_path") or "").strip()
        if not file_path:
            return SkillResult(
                success=False,
                skill_name=self.name,
                summary="未提供 CSV 文件路径。",
                errors=["缺少 file_path 参数。"],
            )

        result = load_raman_csv(Path(file_path))
        if not result.get("success"):
            return SkillResult(
                success=False,
                skill_name=self.name,
                summary="CSV 光谱读取失败。",
                errors=[str(result.get("error_message") or "未知错误")],
            )

        points = int(result.get("points", 0) or 0)
        x_min = result.get("x_min")
        x_max = result.get("x_max")
        summary = f"CSV 光谱读取成功，共 {points} 个有效点。"
        if x_min is not None and x_max is not None:
            summary = f"{summary} 波数范围约为 {float(x_min):.2f} 到 {float(x_max):.2f} cm^-1。"

        return SkillResult(
            success=True,
            skill_name=self.name,
            summary=summary,
            data={
                "file_path": file_path,
                "points": points,
                "x_min": result.get("x_min"),
                "x_max": result.get("x_max"),
                "y_min": result.get("y_min"),
                "y_max": result.get("y_max"),
                "x": result.get("x", []),
                "y": result.get("y", []),
            },
        )
