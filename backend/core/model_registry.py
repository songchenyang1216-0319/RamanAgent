"""Unified model/provider registry loaded from environment variables."""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from dotenv import load_dotenv
from raman_core.methanol.config import PROJECT_ROOT


ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name, "true" if default else "false").lower()
    return value in {"1", "true", "yes", "on"}


def _split_models(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _title_from_model(model_id: str) -> str:
    text = str(model_id or "").strip()
    if not text:
        return "Unknown"
    base = text.split("/")[-1]
    return base


MODEL_CATEGORY_LABELS = {
    "text_chat": "文本对话",
    "vision_understanding": "视觉理解",
    "image_edit": "图像编辑",
    "ocr": "OCR",
    "embedding": "向量检索",
    "audio": "音频",
    "unknown": "待确认",
}

MODEL_CATEGORY_ORDER = [
    "text_chat",
    "vision_understanding",
    "image_edit",
    "ocr",
    "embedding",
    "audio",
    "unknown",
]

_VISION_MODEL_HINTS = (
    "vl",
    "vision",
    "multimodal",
    "omni",
    "u1",
    "qwen3.6-",
    "qwen3.5-",
    "gpt-4o",
    "llava",
    "v1",
)
_IMAGE_EDIT_HINTS = ("image-edit", "img-edit", "paint", "edit")
_OCR_HINTS = ("ocr", "dococr", "layout")
_EMBEDDING_HINTS = ("embed", "embedding", "rerank")
_AUDIO_HINTS = ("audio", "speech", "asr", "tts")

_EXPLICIT_CATEGORY_OVERRIDES: dict[tuple[str, str], list[str]] = {
    ("sensenova", "sensenova-6.7-flash-lite"): ["text_chat", "vision_understanding"],
    ("sensenova", "sensenova-u1"): ["text_chat", "vision_understanding"],
    ("sensenova", "sensenova-u1-fast"): ["text_chat", "vision_understanding"],
    ("qwen", "qwen3.6-plus"): ["text_chat", "vision_understanding"],
    ("qwen", "qwen3.6-flash"): ["text_chat", "vision_understanding"],
    ("qwen", "qwen3.5-plus"): ["text_chat", "vision_understanding"],
    ("qwen", "qwen3.5-flash"): ["text_chat", "vision_understanding"],
    ("qwen", "qwen-image-edit-plus"): ["image_edit"],
    ("gemini", "gemini-2.5-flash"): ["text_chat", "vision_understanding"],
    ("gemini", "gemini-2.5-pro"): ["text_chat", "vision_understanding"],
    ("gemini", "gemini-2.0-flash"): ["text_chat", "vision_understanding"],
    ("openai", "gpt-4o"): ["text_chat", "vision_understanding"],
    ("openai", "gpt-4o-mini"): ["text_chat", "vision_understanding"],
    ("openai", "gpt-4o-mini-2024-07-18"): ["text_chat", "vision_understanding"],
    ("zhipu", "glm-4v"): ["text_chat", "vision_understanding"],
    ("zhipu", "glm-4v-plus"): ["text_chat", "vision_understanding"],
    ("zhipu", "glm-4v-flash"): ["text_chat", "vision_understanding"],
    ("ollama", "llava:7b"): ["text_chat", "vision_understanding"],
    ("siliconflow", "Qwen/Qwen2.5-VL-72B-Instruct"): ["text_chat", "vision_understanding"],
    ("siliconflow", "Qwen/Qwen3-32B"): ["text_chat"],
    ("siliconflow", "Qwen/Qwen3-14B"): ["text_chat"],
    ("siliconflow", "Qwen/Qwen2.5-72B-Instruct"): ["text_chat"],
    ("siliconflow", "deepseek-ai/DeepSeek-V3"): ["text_chat"],
    ("siliconflow", "deepseek-ai/DeepSeek-R1"): ["text_chat"],
    ("siliconflow", "THUDM/GLM-4-9B-0414"): ["text_chat"],
}


def _category_labels(categories: list[str]) -> list[str]:
    ordered = [item for item in MODEL_CATEGORY_ORDER if item in categories]
    extras = [item for item in categories if item not in ordered]
    return [MODEL_CATEGORY_LABELS.get(item, item) for item in ordered + extras]


def _category_summary(categories: list[str]) -> str:
    labels = _category_labels(categories)
    return " / ".join(labels) if labels else "待确认"


def _supported_categories(provider_id: str, model_id: str) -> tuple[list[str], str, str]:
    provider = str(provider_id or "").strip().lower()
    text = str(model_id or "").strip()
    lowered = text.lower()
    override = _EXPLICIT_CATEGORY_OVERRIDES.get((provider, text))
    if override:
        return list(dict.fromkeys(override)), "explicit", "explicit_override"

    categories: list[str] = []
    source = "default"
    reason = "default_text_chat"

    if any(token in lowered for token in _IMAGE_EDIT_HINTS):
        categories = ["image_edit"]
        source = "heuristic"
        reason = "image_edit_hint"
    elif any(token in lowered for token in _OCR_HINTS):
        categories = ["ocr", "vision_understanding"]
        source = "heuristic"
        reason = "ocr_hint"
    elif any(token in lowered for token in _EMBEDDING_HINTS):
        categories = ["embedding"]
        source = "heuristic"
        reason = "embedding_hint"
    elif any(token in lowered for token in _AUDIO_HINTS):
        categories = ["audio"]
        source = "heuristic"
        reason = "audio_hint"
    else:
        vision_hint = any(token in lowered for token in _VISION_MODEL_HINTS)
        if vision_hint:
            categories = ["text_chat", "vision_understanding"]
            source = "heuristic"
            reason = "vision_hint"
        else:
            categories = ["text_chat"]

    if "vision_understanding" in categories and "text_chat" not in categories:
        categories.insert(0, "text_chat")
    if not categories:
        categories = ["unknown"]
        reason = "unclassified"
    return list(dict.fromkeys(categories)), source, reason


def _supports_vision(provider_id: str, model_id: str) -> bool:
    categories, _, _ = _supported_categories(provider_id, model_id)
    return "vision_understanding" in categories


def _model_type(provider_id: str, model_id: str) -> str:
    categories, _, _ = _supported_categories(provider_id, model_id)
    if "vision_understanding" in categories:
        return "vision"
    if "image_edit" in categories:
        return "image_edit"
    if "ocr" in categories:
        return "ocr"
    if "embedding" in categories:
        return "embedding"
    if "audio" in categories:
        return "audio"
    if "text_chat" in categories:
        return "text"
    return "unknown"


def _build_model_record(provider_id: str, model_id: str) -> dict[str, Any]:
    categories, category_source, category_reason = _supported_categories(provider_id, model_id)
    category_labels = _category_labels(categories)
    return {
        "id": model_id,
        "display_name": _title_from_model(model_id),
        "model_type": _model_type(provider_id, model_id),
        "supported_categories": categories,
        "supported_category_labels": category_labels,
        "category_summary": _category_summary(categories),
        "category_source": category_source,
        "category_reason": category_reason,
        "category_status": "confirmed" if category_source in {"explicit", "heuristic"} else "default",
        "supports_chat": "text_chat" in categories or "vision_understanding" in categories,
        "supports_tools": True,
        "supports_vision": "vision_understanding" in categories,
        "endpoint_type": "chat_completions",
    }


class ModelRegistry:
    """Read provider and model metadata from environment variables."""

    def __init__(self) -> None:
        self._providers = self.load_from_env()

    def _provider_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "provider_id": "sensenova",
                "display_name": "商汤日日新 SenseNova",
                "api_key_env": "SENSENOVA_API_KEY",
                "base_url_env": "SENSENOVA_BASE_URL",
                "default_model_env": "SENSENOVA_DEFAULT_MODEL",
                "available_models_env": "SENSENOVA_AVAILABLE_MODELS",
                "default_base_url": "https://token.sensenova.cn/v1",
                "default_model": "sensenova-6.7-flash-lite",
                "default_models": ["sensenova-6.7-flash-lite", "deepseek-v4-flash"],
            },
            {
                "provider_id": "openai",
                "display_name": "OpenAI",
                "api_key_env": "OPENAI_API_KEY",
                "base_url_env": "OPENAI_BASE_URL",
                "default_model_env": "OPENAI_DEFAULT_MODEL",
                "available_models_env": "OPENAI_AVAILABLE_MODELS",
                "default_base_url": "https://api.openai.com/v1",
                "default_model": "gpt-5.4-mini",
                "default_models": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-4.1", "gpt-4.1-mini", "gpt-4o"],
            },
            {
                "provider_id": "qwen",
                "display_name": "通义千问",
                "api_key_env": "QWEN_API_KEY",
                "base_url_env": "QWEN_BASE_URL",
                "default_model_env": "QWEN_DEFAULT_MODEL",
                "available_models_env": "QWEN_AVAILABLE_MODELS",
                "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "default_model": "qwen-plus",
                "default_models": ["qwen-plus", "qwen-flash", "qwen-turbo", "qwen3-coder-plus", "qwen-vl-plus", "qwen2.5-vl-72b-instruct"],
            },
            {
                "provider_id": "zhipu",
                "display_name": "智谱 GLM",
                "api_key_env": "ZHIPU_API_KEY",
                "base_url_env": "ZHIPU_BASE_URL",
                "default_model_env": "ZHIPU_DEFAULT_MODEL",
                "available_models_env": "ZHIPU_AVAILABLE_MODELS",
                "default_base_url": "https://open.bigmodel.cn/api/paas/v4/",
                "default_model": "glm-5-turbo",
                "default_models": ["glm-5", "glm-5-turbo", "glm-4.7", "glm-4.6", "glm-4.5", "glm-4-plus", "glm-4-air", "glm-4-flash", "glm-4v-plus"],
            },
            {
                "provider_id": "siliconflow",
                "display_name": "硅基流动",
                "api_key_env": "SILICONFLOW_API_KEY",
                "base_url_env": "SILICONFLOW_BASE_URL",
                "default_model_env": "SILICONFLOW_DEFAULT_MODEL",
                "available_models_env": "SILICONFLOW_AVAILABLE_MODELS",
                "default_base_url": "https://api.siliconflow.cn/v1",
                "default_model": "Qwen/Qwen3-32B",
                "default_models": ["Qwen/Qwen3-32B", "Qwen/Qwen3-14B", "Qwen/Qwen2.5-72B-Instruct", "Qwen/Qwen2.5-VL-72B-Instruct", "deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "THUDM/GLM-4-9B-0414"],
            },
            {
                "provider_id": "gemini",
                "display_name": "Gemini",
                "api_key_env": "GEMINI_API_KEY",
                "base_url_env": "GEMINI_BASE_URL",
                "default_model_env": "GEMINI_DEFAULT_MODEL",
                "available_models_env": "GEMINI_AVAILABLE_MODELS",
                "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "default_model": "gemini-2.5-flash",
                "default_models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
            },
            {
                "provider_id": "ollama",
                "display_name": "Ollama",
                "api_key_env": "OLLAMA_API_KEY",
                "base_url_env": "OLLAMA_BASE_URL",
                "default_model_env": "OLLAMA_DEFAULT_MODEL",
                "available_models_env": "OLLAMA_AVAILABLE_MODELS",
                "default_base_url": "http://127.0.0.1:11434/v1",
                "default_model": "qwen2.5:7b",
                "default_models": ["qwen2.5:7b", "qwen2.5:14b", "qwen2.5-coder:7b", "llama3.1:8b", "deepseek-r1:7b", "llava:7b"],
            },
        ]

    def load_from_env(self) -> dict[str, dict[str, Any]]:
        load_dotenv(ENV_PATH, override=True)
        providers: dict[str, dict[str, Any]] = {}
        for spec in self._provider_specs():
            provider_id = spec["provider_id"]
            api_key = _env(spec["api_key_env"])
            base_url = _env(spec["base_url_env"], spec["default_base_url"])
            available_models = _split_models(_env(spec["available_models_env"])) or list(spec["default_models"])
            default_model = _env(spec["default_model_env"], spec["default_model"])
            if default_model not in available_models and available_models:
                default_model = available_models[0]
            configured = bool(base_url) if provider_id == "ollama" else bool(api_key)
            reason = ""
            if not base_url:
                reason = f"{spec['base_url_env']} 未配置"
            elif provider_id != "ollama" and not api_key:
                reason = f"{spec['api_key_env']} 未配置"

            providers[provider_id] = {
                "provider_id": provider_id,
                "display_name": spec["display_name"],
                "api_key_env": spec["api_key_env"],
                "base_url_env": spec["base_url_env"],
                "default_model_env": spec["default_model_env"],
                "available_models_env": spec["available_models_env"],
                "api_key": api_key,
                "base_url": base_url,
                "default_model": default_model,
                "available_models": available_models,
                "enabled": bool(base_url),
                "configured": configured,
                "reason": reason,
                "models": [_build_model_record(provider_id, model_id) for model_id in available_models],
            }
        return providers

    def reload(self) -> None:
        self._providers = self.load_from_env()

    def list_providers(self) -> list[dict[str, Any]]:
        items = []
        for provider in self._providers.values():
            items.append(
                {
                    "provider_id": provider["provider_id"],
                    "display_name": provider["display_name"],
                    "enabled": provider["enabled"],
                    "configured": provider["configured"],
                    "default_model": provider["default_model"],
                    "reason": provider["reason"],
                    "api_key_env": provider["api_key_env"],
                }
            )
        return items

    def list_models(self, provider_id: str) -> list[dict[str, Any]]:
        provider = self.get_provider_config(provider_id)
        return deepcopy(provider.get("models") or [])

    def get_model_meta(self, provider_id: str, model_id: str) -> dict[str, Any]:
        provider = self.get_provider_config(provider_id)
        for item in provider.get("models") or []:
            if str(item.get("id") or "") == str(model_id or ""):
                return deepcopy(item)
        return {}

    def list_available_vision_models(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for provider in self._providers.values():
            if not provider.get("configured"):
                continue
            for model in provider.get("models") or []:
                if model.get("supports_vision"):
                    items.append(
                        {
                            "provider_id": provider.get("provider_id"),
                            "provider_name": provider.get("display_name"),
                            "model_id": model.get("id"),
                            "display_name": f"{provider.get('display_name')} · {model.get('display_name') or model.get('id')}",
                            "supports_vision": True,
                            "supported_categories": list(model.get("supported_categories") or []),
                            "supported_category_labels": list(model.get("supported_category_labels") or []),
                            "category_summary": model.get("category_summary") or "",
                        }
                    )
        return items

    def get_provider_config(self, provider_id: str) -> dict[str, Any]:
        provider = self._providers.get(str(provider_id or "").strip())
        if provider is None:
            raise KeyError(f"平台不存在: {provider_id}")
        return deepcopy(provider)

    def get_default_model(self, provider_id: str) -> str:
        return str(self.get_provider_config(provider_id).get("default_model") or "")

    def validate_provider(self, provider_id: str) -> tuple[bool, str]:
        if str(provider_id or "").strip() not in self._providers:
            return False, "平台不存在，请重新选择。"
        return True, ""

    def validate_model(self, provider_id: str, model_id: str) -> tuple[bool, str]:
        ok, message = self.validate_provider(provider_id)
        if not ok:
            return ok, message
        provider = self.get_provider_config(provider_id)
        model_ids = [item["id"] for item in provider.get("models") or []]
        if str(model_id or "").strip() not in model_ids:
            return False, "当前平台不支持该模型，请重新选择。"
        return True, ""

    def get_current_provider(self) -> str:
        provider = _env("LLM_PROVIDER", "sensenova").lower()
        if provider in self._providers:
            return provider
        return "sensenova"

    def get_current_model(self) -> str:
        provider_id = self.get_current_provider()
        provider = self.get_provider_config(provider_id)
        model = _env("LLM_MODEL", provider.get("default_model") or "")
        if model in provider.get("available_models", []):
            return model
        return str(provider.get("default_model") or "")

    def get_refresh_settings(self) -> dict[str, Any]:
        return {
            "enabled": _env_bool("MODEL_REFRESH_ENABLED", True),
            "timeout_seconds": int(_env("MODEL_REFRESH_TIMEOUT_SECONDS", "20") or "20"),
            "cache_seconds": int(_env("MODEL_REFRESH_CACHE_SECONDS", "3600") or "3600"),
        }
