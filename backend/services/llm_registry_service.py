"""Compatibility wrapper around the new provider/model registry."""

from __future__ import annotations

from typing import Any

from backend.core.model_registry import ModelRegistry
from backend.core.model_router import ModelRouter


class LLMRegistryService:
    """兼容旧调用方，同时把核心逻辑委托给 ModelRegistry/ModelRouter。"""

    def __init__(self) -> None:
        self.registry = ModelRegistry()
        self.router = ModelRouter(registry=self.registry)

    def list_models(self) -> dict[str, Any]:
        current = self.router.get_selected_model()
        providers = self.registry.list_providers()
        models = []
        for provider in providers:
            for model in self.registry.list_models(provider["provider_id"]):
                models.append(
                    {
                        "provider": provider["provider_id"],
                        "provider_display_name": provider["display_name"],
                        "model": model["id"],
                        "model_display_name": model["display_name"],
                        "display_name": f"{provider['display_name']} · {model['display_name']}",
                        "available": provider["configured"] or provider["provider_id"] == "ollama",
                        "reason": provider.get("reason") or "",
                        "current": provider["provider_id"] == current["provider_id"] and model["id"] == current["model_id"],
                        "api_key_env": self.registry.get_provider_config(provider["provider_id"]).get("api_key_env"),
                        "base_url": self.registry.get_provider_config(provider["provider_id"]).get("base_url"),
                    }
                )
        return {
            "success": True,
            "current": {
                "provider": current["provider_id"],
                "provider_display_name": current["provider_name"],
                "model": current["model_id"],
                "model_display_name": current["model_name"],
                "display_name": f"{current['provider_name']} · {current['model_name']}",
                "available": current["configured"] or current["provider_id"] == "ollama",
                "reason": current.get("reason") or "",
                "api_key_env": current["provider_config"].get("api_key_env"),
                "base_url": current["provider_config"].get("base_url"),
            },
            "models": models,
        }

    def get_current_model(self) -> dict[str, Any]:
        current = self.router.get_selected_model()
        return {
            "success": True,
            "current": {
                "provider": current["provider_id"],
                "provider_display_name": current["provider_name"],
                "model": current["model_id"],
                "model_display_name": current["model_name"],
                "display_name": f"{current['provider_name']} · {current['model_name']}",
                "available": current["configured"] or current["provider_id"] == "ollama",
                "reason": current.get("reason") or "",
                "api_key_env": current["provider_config"].get("api_key_env"),
                "base_url": current["provider_config"].get("base_url"),
            },
        }

    def get_current_model_info(self) -> dict[str, Any]:
        current = self.router.get_selected_model()
        return {
            "provider": current["provider_id"],
            "provider_display_name": current["provider_name"],
            "model": current["model_id"],
            "model_display_name": current["model_name"],
            "display_name": f"{current['provider_name']} · {current['model_name']}",
            "available": current["configured"] or current["provider_id"] == "ollama",
            "reason": current.get("reason") or "",
            "api_key_env": current["provider_config"].get("api_key_env"),
            "base_url": current["provider_config"].get("base_url"),
        }

    def get_provider_config(self) -> dict[str, Any]:
        current = self.router.get_selected_model()
        provider = current["provider_config"]
        return {
            "provider": current["provider_id"],
            "provider_display_name": current["provider_name"],
            "model": current["model_id"],
            "model_display_name": current["model_name"],
            "display_name": f"{current['provider_name']} · {current['model_name']}",
            "api_key_env": provider.get("api_key_env"),
            "base_url_env": provider.get("base_url_env"),
            "base_url": provider.get("base_url"),
            "api_key": provider.get("api_key"),
            "available": current["configured"] or current["provider_id"] == "ollama",
            "reason": current.get("reason") or "",
        }

    def switch_current_model(self, provider: str, model: str) -> dict[str, Any]:
        try:
            current = self.router.set_selected_model(provider, model)
        except ValueError as exc:
            return {"success": False, "error_message": str(exc), "current": self.get_current_model().get("current")}
        return {
            "success": True,
            "current": {
                "provider": current["provider_id"],
                "provider_display_name": current["provider_name"],
                "model": current["model_id"],
                "model_display_name": current["model_name"],
                "display_name": f"{current['provider_name']} · {current['model_name']}",
                "available": current["configured"] or current["provider_id"] == "ollama",
                "reason": current.get("reason") or "",
                "api_key_env": current["provider_config"].get("api_key_env"),
                "base_url": current["provider_config"].get("base_url"),
            },
        }
