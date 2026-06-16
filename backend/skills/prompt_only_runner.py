from __future__ import annotations

from typing import Any

from backend.schemas.agent_response import AgentResponse
from backend.skills.skill_registry import SkillRegistry


class PromptOnlySkillRunner:
    def __init__(self) -> None:
        self.registry = SkillRegistry()

    def run(self, skill_name: str, normalized_message, **kwargs: Any) -> AgentResponse:
        result = self.registry.execute(
            skill_name,
            action_name="run_uploaded_skill",
            file_path=normalized_message.file_path,
            file_paths=[
                str(item.get("path") or item.get("file_path") or "")
                for item in getattr(normalized_message, "files", []) or []
                if str(item.get("path") or item.get("file_path") or "").strip()
            ],
            files=list(getattr(normalized_message, "files", []) or []),
            file_ids=list(getattr(normalized_message, "file_ids", []) or []),
            session_id=normalized_message.session_id,
            message=normalized_message.message,
            original_message=normalized_message.message,
            task_type=kwargs.get("task_type"),
            metadata=normalized_message.metadata,
            provider_id=normalized_message.provider_id,
            model_id=normalized_message.model_id,
            user_id=normalized_message.user_id,
            conversation_id=normalized_message.conversation_id,
        )
        reply = str(result.data.get("reply_text") or result.summary or "").strip()
        error_message = "；".join(result.errors) if result.errors else None
        return AgentResponse(
            success=bool(reply) or result.success,
            reply=reply,
            skill_used=True,
            skill_name=skill_name,
            skill_mode="prompt_only",
            action_name=result.action_name or "run_uploaded_skill",
            data=dict(result.data or {}),
            debug={"runner": "prompt_only_runner"},
            error_message=None if (bool(reply) or result.success) else error_message,
            source="skill_execution",
        )
