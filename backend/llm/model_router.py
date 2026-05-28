from __future__ import annotations

from typing import Any

from backend.core.model_router import ModelRouter as CoreModelRouter


class ModelRouter:
    def __init__(self) -> None:
        self.core_router = CoreModelRouter()

    def chat(
        self,
        messages: list[dict[str, Any]],
        provider: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        response, selection = self.core_router.chat(
            messages,
            provider_id=provider,
            model_id=model,
            user_id=user_id,
            conversation_id=conversation_id,
            stream=kwargs.get("stream", False),
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
            timeout_seconds=kwargs.get("timeout_seconds"),
        )
        content = ""
        if getattr(response, "choices", None):
            content = str(response.choices[0].message.content or "").strip()
        return content, selection

