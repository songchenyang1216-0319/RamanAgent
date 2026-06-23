from __future__ import annotations

import json
from dataclasses import dataclass, field

from fastapi import Request, UploadFile


@dataclass
class ParsedChatRequest:
    message: str = ""
    conversation_id: str | None = None
    user_id: str = ""
    debug: bool = False
    uploaded_files: list[UploadFile] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)
    knowledge_base_ids: list[str] = field(default_factory=list)
    rag_scope: str | None = None
    metadata: dict[str, str | None] = field(default_factory=dict)
    provider_id: str | None = None
    model_id: str | None = None
    request_content_type: str = ""


class ChatRequestParser:
    def __init__(self, *, default_user_id: str) -> None:
        self.default_user_id = default_user_id

    async def parse(self, request: Request) -> ParsedChatRequest:
        content_type = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            uploaded_file = form.get("file")
            return ParsedChatRequest(
                message=str(form.get("message") or "").strip(),
                conversation_id=str(form.get("conversation_id") or form.get("session_id") or "").strip() or None,
                user_id=str(form.get("user_id") or self.default_user_id).strip() or self.default_user_id,
                provider_id=str(form.get("provider_id") or "").strip() or None,
                model_id=str(form.get("model_id") or "").strip() or None,
                debug=self._as_bool(form.get("debug")),
                uploaded_files=self._dedupe_uploaded_files([uploaded_file, *list(form.getlist("files") or [])]),
                file_ids=self._normalize_string_list(form.get("file_ids") or form.getlist("file_ids")),
                knowledge_base_ids=self._normalize_string_list(form.get("knowledge_base_ids") or form.getlist("knowledge_base_ids")),
                rag_scope=str(form.get("rag_scope") or "").strip() or None,
                metadata={
                    "sample_name": str(form.get("sample_name") or "").strip() or None,
                    "sample_type": str(form.get("sample_type") or "").strip() or None,
                    "operator": str(form.get("operator") or "").strip() or None,
                    "instrument": str(form.get("instrument") or "").strip() or None,
                    "laser_power": str(form.get("laser_power") or "").strip() or None,
                    "integration_time": str(form.get("integration_time") or "").strip() or None,
                    "remarks": str(form.get("remark") or form.get("remarks") or "").strip() or None,
                },
                request_content_type=content_type,
            )

        payload = await request.json()
        return ParsedChatRequest(
            message=str(payload.get("message") or "").strip(),
            conversation_id=payload.get("conversation_id") or payload.get("session_id"),
            user_id=str(payload.get("user_id") or self.default_user_id).strip() or self.default_user_id,
            provider_id=str(payload.get("provider_id") or "").strip() or None,
            model_id=str(payload.get("model_id") or "").strip() or None,
            debug=bool(payload.get("debug", False)),
            file_ids=self._normalize_string_list(payload.get("file_ids")),
            knowledge_base_ids=self._normalize_string_list(payload.get("knowledge_base_ids")),
            rag_scope=str(payload.get("rag_scope") or "").strip() or None,
            request_content_type=content_type,
        )

    @staticmethod
    def _normalize_string_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
                raw_items = parsed if isinstance(parsed, list) else text.split(",")
            except Exception:
                raw_items = text.split(",")
        elif isinstance(value, (list, tuple, set)):
            raw_items = list(value)
        else:
            raw_items = [value]

        result = []
        seen = set()
        for item in raw_items:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _dedupe_uploaded_files(items: list[object]) -> list[UploadFile]:
        result: list[UploadFile] = []
        seen = set()
        for item in items:
            if not getattr(item, "filename", "") or not hasattr(item, "read"):
                continue
            key = (id(item), getattr(item, "filename", ""))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _as_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
