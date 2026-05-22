"""工件检查工具。"""

from __future__ import annotations

from backend.services.model_registry_service import ModelRegistryService


def check_artifacts_tool() -> dict:
    """检查模型工件是否齐全，并返回结构化结果。"""
    service = ModelRegistryService()
    result = service.check_model_artifacts()
    if not result.get("success") and result.get("data") is None:
        return result

    data = result.get("data") or {}
    return {
        "success": bool(result.get("success")),
        "model_version": data.get("model_version"),
        "artifact_dir": data.get("artifact_dir"),
        "missing_files": data.get("missing_files", []),
        "existing_files": data.get("existing_files", []),
        "fallback_files": data.get("fallback_files", []),
        "warnings": result.get("warnings", []),
    }
