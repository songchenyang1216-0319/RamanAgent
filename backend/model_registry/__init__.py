"""模型注册表兼容导出。"""

from __future__ import annotations

__all__ = ["ModelRegistryService"]


def __getattr__(name: str):
    if name == "ModelRegistryService":
        from .model_registry_service import ModelRegistryService

        return ModelRegistryService
    raise AttributeError(name)
