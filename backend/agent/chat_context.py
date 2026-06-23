from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import UploadFile


@dataclass
class ChatExecutionContext:
    message: str
    effective_message: str
    user_id: str
    conversation_id: str
    session_id: str
    provider_id: str | None = None
    model_id: str | None = None
    debug: bool = False
    metadata: dict[str, str | None] = field(default_factory=dict)
    rag_scope: str | None = None
    file_ids: list[str] = field(default_factory=list)
    knowledge_base_ids: list[str] = field(default_factory=list)
    uploaded_files: list[UploadFile] = field(default_factory=list, repr=False)
    selected_files: list[dict] = field(default_factory=list)
    orchestrator_payload: dict[str, object] = field(default_factory=dict)
    workspace_context: dict = field(default_factory=dict)
    user_memory: dict = field(default_factory=dict)
    request_content_type: str = ""
    user_message_id: str | None = None
    persistence_state: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: uuid4().hex)
    turn_id: str = field(default_factory=lambda: uuid4().hex)

    def to_orchestrator_payload(self) -> dict[str, object]:
        payload = dict(self.orchestrator_payload)
        payload.setdefault("message", self.effective_message)
        payload.setdefault("conversation_id", self.conversation_id)
        payload.setdefault("session_id", self.session_id)
        payload.setdefault("user_id", self.user_id)
        payload.setdefault("provider_id", self.provider_id)
        payload.setdefault("model_id", self.model_id)
        payload.setdefault("debug", self.debug)
        payload.setdefault("metadata", dict(self.metadata or {}))
        payload.setdefault("file_ids", list(self.file_ids or []))
        payload.setdefault("knowledge_base_ids", list(self.knowledge_base_ids or []))
        payload.setdefault("rag_scope", self.rag_scope)
        payload.setdefault("explicit_has_file", bool(self.uploaded_files or self.file_ids))
        if self.selected_files:
            payload.setdefault("files", list(self.selected_files))
        return payload
