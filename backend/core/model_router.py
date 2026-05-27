"""Route chat requests through the selected provider/model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.model_registry import ModelRegistry
from backend.services.user_memory_manager import UserMemoryManager
from backend.services.workspace_manager import DEFAULT_USER_ID, WorkspaceManager
from raman_core.methanol.config import PROJECT_ROOT


LEGACY_SELECTION_PATH = PROJECT_ROOT / "backend" / "data" / "llm_config.json"


class ModelRouter:
    """Resolve selection precedence and construct provider clients."""

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        workspace_manager: WorkspaceManager | None = None,
        user_memory_manager: UserMemoryManager | None = None,
    ) -> None:
        self.registry = registry or ModelRegistry()
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.user_memory_manager = user_memory_manager or UserMemoryManager()

    def _read_workspace_selection(self, user_id: str | None, conversation_id: str | None) -> tuple[str | None, str | None]:
        if not conversation_id:
            return None, None
        task_state = self.workspace_manager.read_task_state(user_id or DEFAULT_USER_ID, conversation_id)
        provider_id = str(task_state.get("selected_provider") or "").strip() or None
        model_id = str(task_state.get("selected_model") or "").strip() or None
        return provider_id, model_id

    def _write_workspace_selection(self, user_id: str | None, conversation_id: str | None, provider_id: str, model_id: str) -> None:
        if not conversation_id:
            return
        task_state = self.workspace_manager.read_task_state(user_id or DEFAULT_USER_ID, conversation_id)
        task_state["selected_provider"] = provider_id
        task_state["selected_model"] = model_id
        self.workspace_manager.update_task_state(user_id or DEFAULT_USER_ID, conversation_id, task_state)

    def _read_user_preference(self, user_id: str | None) -> tuple[str | None, str | None]:
        memory = self.user_memory_manager.get_user_memory(user_id or DEFAULT_USER_ID)
        provider_id = str(memory.get("preferred_provider") or "").strip() or None
        model_id = str(memory.get("preferred_model") or "").strip() or None
        return provider_id, model_id

    def _write_legacy_selection(self, provider_id: str, model_id: str) -> None:
        LEGACY_SELECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
        LEGACY_SELECTION_PATH.write_text(
            json.dumps({"current": {"provider": provider_id, "model": model_id}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_legacy_selection(self) -> tuple[str | None, str | None]:
        if not LEGACY_SELECTION_PATH.exists():
            return None, None
        try:
            payload = json.loads(LEGACY_SELECTION_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None, None
        current = payload.get("current") or {}
        return str(current.get("provider") or "").strip() or None, str(current.get("model") or "").strip() or None

    def resolve_selection(
        self,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        self.registry.reload()
        requested_provider = str(provider_id or "").strip() or None
        requested_model = str(model_id or "").strip() or None
        workspace_provider, workspace_model = self._read_workspace_selection(user_id, conversation_id)
        preferred_provider, preferred_model = self._read_user_preference(user_id)
        legacy_provider, legacy_model = self._read_legacy_selection()
        env_provider = self.registry.get_current_provider()
        env_model = self.registry.get_current_model()
        resolved_provider = (
            requested_provider
            or workspace_provider
            or preferred_provider
            or env_provider
            or legacy_provider
        )
        provider_ok, provider_error = self.registry.validate_provider(resolved_provider)
        if not provider_ok:
            raise ValueError(provider_error)
        provider = self.registry.get_provider_config(resolved_provider)
        resolved_model = (
            requested_model
            or workspace_model
            or preferred_model
            or env_model
            or legacy_model
            or provider.get("default_model")
        )
        model_ok, model_error = self.registry.validate_model(resolved_provider, resolved_model)
        if not model_ok:
            resolved_model = str(provider.get("default_model") or "")
            model_ok, model_error = self.registry.validate_model(resolved_provider, resolved_model)
        if not model_ok:
            raise ValueError(model_error)
        model_meta = next((item for item in provider.get("models") or [] if item.get("id") == resolved_model), {})
        return {
            "provider_id": resolved_provider,
            "provider_name": provider.get("display_name"),
            "provider_config": provider,
            "model_id": resolved_model,
            "model_name": model_meta.get("display_name") or resolved_model,
            "model_meta": model_meta,
            "model_type": model_meta.get("model_type") or "unknown",
            "supports_vision": bool(model_meta.get("supports_vision")),
            "supported_categories": list(model_meta.get("supported_categories") or []),
            "supported_category_labels": list(model_meta.get("supported_category_labels") or []),
            "category_summary": model_meta.get("category_summary") or "",
            "category_source": model_meta.get("category_source") or "",
            "category_reason": model_meta.get("category_reason") or "",
            "category_status": model_meta.get("category_status") or "",
            "configured": provider.get("configured"),
            "enabled": provider.get("enabled"),
            "reason": provider.get("reason") or "",
        }

    def get_selected_model(self, user_id: str | None = None, conversation_id: str | None = None) -> dict[str, Any]:
        return self.resolve_selection(user_id=user_id, conversation_id=conversation_id)

    def set_selected_model(
        self,
        provider_id: str,
        model_id: str,
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        selection = self.resolve_selection(
            provider_id=provider_id,
            model_id=model_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        provider = selection["provider_config"]
        if not provider.get("base_url"):
            raise ValueError("当前平台 BASE_URL 未配置，请检查 .env。")
        if selection["provider_id"] != "ollama" and not provider.get("api_key"):
            raise ValueError(f"当前平台 API Key 未配置，请在 .env 中填写 {provider.get('api_key_env')}。")
        if conversation_id:
            self._write_workspace_selection(user_id, conversation_id, selection["provider_id"], selection["model_id"])
        else:
            self.user_memory_manager.set_preferred_model(
                user_id or DEFAULT_USER_ID,
                selection["model_id"],
                provider_id=selection["provider_id"],
            )
            self._write_legacy_selection(selection["provider_id"], selection["model_id"])
        return selection

    def create_client(self, provider_id: str) -> Any:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError("未安装 openai 依赖，请执行 pip install -r requirements.txt。") from exc

        provider = self.registry.get_provider_config(provider_id)
        base_url = str(provider.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("当前平台 BASE_URL 未配置，请检查 .env。")
        api_key = str(provider.get("api_key") or "").strip()
        if provider_id == "ollama":
            api_key = api_key or "ollama"
        elif not api_key:
            raise ValueError(f"当前平台 API Key 未配置，请在 .env 中填写 {provider.get('api_key_env')}。")
        return OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: list[dict[str, Any]],
        provider_id: str | None = None,
        model_id: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        stream: bool | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: int | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        selection = self.resolve_selection(
            provider_id=provider_id,
            model_id=model_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        provider = selection["provider_config"]
        if not provider.get("base_url"):
            raise ValueError("当前平台 BASE_URL 未配置，请检查 .env。")
        if selection["provider_id"] != "ollama" and not provider.get("api_key"):
            raise ValueError(f"当前平台 API Key 未配置，请在 .env 中填写 {provider.get('api_key_env')}。")
        client = self.create_client(selection["provider_id"])
        response = client.chat.completions.create(
            model=selection["model_id"],
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=bool(stream) if stream is not None else False,
            timeout=timeout_seconds,
        )
        return response, selection
