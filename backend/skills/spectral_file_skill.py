"""光谱文件处理大 Skill。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agent.tools.spectral_tools.spectrum_loader import load_raman_csv

from .base import BaseSkill, SkillResult


class SpectralFileSkill(BaseSkill):
    """负责对外暴露 CSV 光谱读取与校验能力。"""

    name = "spectral_file_skill"
    display_name = "光谱文件处理"
    description = "负责读取、校验和解析拉曼光谱 CSV 文件，包括文件格式检查、列数检查、空值检查、波数范围和强度范围统计。"
    category = "数据处理"
    requires_file = True
    supported_file_types = ["csv"]
    usage = "上传 CSV 后，可以先调用这个 Skill 做基础读取和校验。"
    actions = [
        {
            "name": "load_csv",
            "display_name": "读取 CSV",
            "description": "读取拉曼光谱 CSV，并返回基础数组结果。",
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        },
        {
            "name": "validate_csv",
            "display_name": "校验 CSV",
            "description": "检查文件后缀、列数、空值和有效点数。",
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        },
        {
            "name": "inspect_spectrum",
            "display_name": "检查光谱范围",
            "description": "统计波数范围、强度范围和点数。",
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        },
        {
            "name": "extract_metadata",
            "display_name": "提取基础元数据",
            "description": "从 CSV 中提取光谱基础信息，供后续分析使用。",
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        },
    ]

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "inspect_spectrum")
        file_path = str(kwargs.get("file_path") or "").strip()
        if not file_path:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="未提供 CSV 文件路径。",
                errors=["缺少 file_path 参数。"],
            )

        result = load_raman_csv(Path(file_path))
        if not result.get("success"):
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="CSV 文件处理失败。",
                errors=[str(result.get("error_message") or "未知错误")],
            )

        summary = f"CSV 文件处理完成，共 {int(result.get('points', 0) or 0)} 个有效点。"
        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=action_name,
            summary=summary,
            data={
                "file_path": file_path,
                "points": int(result.get("points", 0) or 0),
                "x_min": result.get("x_min"),
                "x_max": result.get("x_max"),
                "y_min": result.get("y_min"),
                "y_max": result.get("y_max"),
                "x": result.get("x", []),
                "y": result.get("y", []),
            },
        )
