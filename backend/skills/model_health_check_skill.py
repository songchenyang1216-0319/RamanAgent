"""模型健康检查 Skill。"""

from __future__ import annotations

from typing import Any

from backend.services.methanol_service import get_predictor
from backend.services.model_registry_service import ModelRegistryService

from .base import BaseSkill, SkillResult


class ModelHealthCheckSkill(BaseSkill):
    """检查模型配置、工件文件和可加载状态。"""

    name = "model_health_check_skill"
    description = "检查当前模型信息、模型文件齐全性和预测器是否可加载。"

    def __init__(self) -> None:
        self._registry_service = ModelRegistryService()

    def run(self, **kwargs: Any) -> SkillResult:
        model_version = kwargs.get("model_version")
        check_loadable = bool(kwargs.get("check_loadable", True))

        model_response = (
            self._registry_service.get_model_version(str(model_version))
            if model_version
            else self._registry_service.get_default_model()
        )
        if not model_response.get("success"):
            return SkillResult(
                success=False,
                skill_name=self.name,
                summary="模型信息读取失败。",
                errors=[str(model_response.get("error_message") or "未知错误")],
            )

        model_info = dict(model_response.get("data") or {})
        artifact_response = self._registry_service.check_model_artifacts(model_info.get("model_version"))
        artifact_data = dict(artifact_response.get("data") or {})
        errors: list[str] = []
        loadable = None

        if check_loadable:
            try:
                get_predictor()
                loadable = True
            except Exception as exc:
                loadable = False
                errors.append(str(exc))

        missing_files = list(artifact_data.get("missing_files") or [])
        success = len(missing_files) == 0 and (loadable is not False)
        summary = f"当前模型为 {model_info.get('model_version') or '未知版本'}。"
        if missing_files:
            summary += f" 发现 {len(missing_files)} 个缺失文件。"
        else:
            summary += " 模型工件检查通过。"
        if loadable is True:
            summary += " 预测器可正常加载。"
        elif loadable is False:
            summary += " 预测器加载失败。"

        return SkillResult(
            success=success,
            skill_name=self.name,
            summary=summary,
            data={
                "model_version": model_info.get("model_version"),
                "model_name": model_info.get("model_name"),
                "artifact_dir": model_info.get("artifact_dir"),
                "missing_files": missing_files,
                "existing_files": list(artifact_data.get("existing_files") or []),
                "fallback_files": list(artifact_data.get("fallback_files") or []),
                "warnings": list(dict.fromkeys((model_response.get("warnings") or []) + (artifact_response.get("warnings") or []))),
                "loadable": loadable,
            },
            errors=errors,
        )
