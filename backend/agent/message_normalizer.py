from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agent.types import NormalizedMessage
from backend.skills.data_analysis_skill import detect_raman_table_signal, is_supported_table_suffix


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DOCUMENT_SUFFIXES = {".txt", ".md", ".markdown", ".docx", ".pdf", ".html", ".htm"}
RAMAN_SUFFIXES = {".spc", ".spa"}


class MessageNormalizer:
    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage:
        message = str(payload.get("message") or "").strip()
        file_path = str(payload.get("file_path") or "").strip() or None
        path = Path(file_path) if file_path else None
        file_suffix = (path.suffix.lower() if path else "") or None
        file_name = path.name if path else None
        file_type = self._detect_file_type(path, file_suffix, message)
        conversation_id = str(payload.get("conversation_id") or payload.get("session_id") or "").strip()
        user_id = str(payload.get("user_id") or "default_user").strip() or "default_user"
        model_id = str(payload.get("model_id") or "").strip() or None
        provider_id = str(payload.get("provider_id") or "").strip() or None
        enabled_skills = [str(item).strip() for item in (payload.get("enabled_skills") or []) if str(item).strip()]
        metadata = dict(payload.get("metadata") or {})
        selected_model = {
            "provider_id": provider_id,
            "model_id": model_id,
        }
        return NormalizedMessage(
            message=message or ("请分析这个文件" if file_path else ""),
            raw_message=str(payload.get("message") or ""),
            conversation_id=conversation_id,
            session_id=conversation_id,
            user_id=user_id,
            debug=bool(payload.get("debug", False)),
            provider_id=provider_id,
            model_id=model_id,
            selected_model=selected_model,
            enabled_skills=enabled_skills,
            workspace_id=str(payload.get("workspace_id") or conversation_id or "").strip() or None,
            metadata=metadata,
            file_path=file_path,
            file_name=file_name,
            file_suffix=file_suffix,
            file_type=file_type,
            has_file=bool(file_path),
        )

    def _detect_file_type(self, path: Path | None, suffix: str | None, message: str) -> str | None:
        suffix = str(suffix or "").lower()
        if not path or not suffix:
            return None
        if suffix in IMAGE_SUFFIXES:
            return "image"
        if suffix in DOCUMENT_SUFFIXES:
            return "document"
        if suffix in RAMAN_SUFFIXES:
            return "raman"
        if is_supported_table_suffix(suffix):
            if any(keyword in str(message or "").lower() for keyword in ("raman", "sers", "光谱", "峰位", "甲醇")):
                return "raman"
            signal = detect_raman_table_signal(path)
            return "raman" if signal.get("is_raman") else "table"
        return "file"

